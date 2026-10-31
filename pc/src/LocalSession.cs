using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;

namespace DotAbyss.Local.Pc;

internal sealed class LocalSession : IDisposable
{
    private readonly HttpClient client;
    private readonly string profile;
    private readonly object gate = new();
    private SessionData? session;

    internal LocalSession(Uri origin, LocalOptions options, HttpMessageHandler? handler = null)
    {
        client = new HttpClient(handler ?? new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false })
        {
            BaseAddress = origin,
            Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds),
            MaxResponseContentBufferSize = AdminSyncSnapshot.MaxPayloadBytes
        };
        profile = options.Profile;
    }

    internal SessionData Get()
    {
        lock (gate) return session ??= CreateAsync().ConfigureAwait(false).GetAwaiter().GetResult();
    }

    internal void VerifyServer() => VerifyServerAsync().ConfigureAwait(false).GetAwaiter().GetResult();

    private async Task VerifyServerAsync()
    {
        using var deadline = new CancellationTokenSource(client.Timeout);
        using var response = await client.GetAsync("/diagnostics", deadline.Token).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(deadline.Token).ConfigureAwait(false));
        var binding = VerifyBinding(document.RootElement);
        using var request = new HttpRequestMessage(HttpMethod.Get, binding.CatalogHash.Path);
        using var hashResponse = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false);
        hashResponse.EnsureSuccessStatusCode();
        if (!hashResponse.Headers.TryGetValues("X-Asset-Revision", out var revisions)
            || !revisions.SequenceEqual(new[] { binding.Revision })
            || hashResponse.Content.Headers.ContentLength is long length && length != binding.CatalogHash.Bytes)
            throw new InvalidDataException("The local resource snapshot changed during startup; retry after the update completes.");
        using var stream = await hashResponse.Content.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false);
        var payload = new byte[binding.CatalogHash.Bytes + 1];
        var used = 0;
        int read;
        while ((read = await stream.ReadAsync(payload.AsMemory(used), deadline.Token).ConfigureAwait(false)) != 0)
        {
            used += read;
            if (used > binding.CatalogHash.Bytes) throw new InvalidDataException("The local catalog hash exceeds its bound size.");
        }
        binding.VerifyCatalogHash(payload.AsSpan(0, used));
    }

    internal static ContentBinding VerifyBinding(JsonElement status) => ContentBinding.Parse(status);

    internal void RegisterRuntime(string appCode, string bundle, string applicationVersion)
    {
        if (applicationVersion != ClientIdentity.ApplicationVersion || string.IsNullOrWhiteSpace(appCode) || bundle != ClientBuildProfile.BundleVersion)
            throw new InvalidDataException("The native runtime does not match the prepared client.");
        using var response = client.PostAsJsonAsync("/local/runtime", new
        {
            app_version_code = appCode,
            bundle_version = bundle,
            application_version = applicationVersion
        }).ConfigureAwait(false).GetAwaiter().GetResult();
        response.EnsureSuccessStatusCode();
    }

    internal void Report(string eventName, object details)
    {
        using var request = Authenticated(HttpMethod.Post, "/local/diagnostics", new { component = "pc-adapter", @event = eventName, details });
        using var response = client.SendAsync(request).ConfigureAwait(false).GetAwaiter().GetResult();
        response.EnsureSuccessStatusCode();
    }

    internal async Task<AdminSyncSnapshot> PollAdminSync(long after, string clientId, CancellationToken cancellation = default)
    {
        if (after < 0) throw new ArgumentOutOfRangeException(nameof(after));
        var identity = Get();
        var path = "/local/admin-sync?after=" + after.ToString(CultureInfo.InvariantCulture)
            + "&client_id=" + AdminSyncPolicy.ClientId(clientId);
        using var request = Authenticated(HttpMethod.Get, path);
        using var response = await client.SendAsync(request, cancellation).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadAsByteArrayAsync(cancellation).ConfigureAwait(false);
        return AdminSyncSnapshot.Parse(payload, identity.UserId);
    }

    internal async Task AcknowledgeAdminSync(AdminSyncAck acknowledgement, CancellationToken cancellation = default)
    {
        AdminSyncPolicy.ClientId(acknowledgement.client_id);
        if (acknowledgement.revision < 0 || acknowledgement.status is not ("applied" or "waiting_safe_point" or "relogin_required" or "failed"))
            throw new InvalidDataException("Invalid administrator synchronization acknowledgement.");
        using var request = Authenticated(HttpMethod.Post, "/local/admin-sync/ack", acknowledgement);
        using var response = await client.SendAsync(request, cancellation).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
    }

    internal GameLoginData AuthenticateGameLogin()
    {
        var identity = Get();
        using var request = Authenticated(HttpMethod.Post, "/login", new { token = identity.Token });
        using var response = client.SendAsync(request).ConfigureAwait(false).GetAwaiter().GetResult();
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(response.Content.ReadAsStringAsync().ConfigureAwait(false).GetAwaiter().GetResult());
        var root = document.RootElement;
        ValidateEnvelope(root);
        var contents = root.GetProperty("contents");
        if (contents.GetProperty("user_id").GetInt64() != identity.UserId
            || contents.GetProperty("uuid").GetString() != identity.Uuid
            || contents.GetProperty("token").GetString() != identity.Token
            || root.GetProperty("api_token").GetString() != identity.ApiToken
            || contents.GetProperty("token_status").GetInt32() != 0)
            throw new InvalidDataException("Game login did not preserve the established local identity.");
        var serverTime = root.GetProperty("server_time").GetString();
        if (!DateTimeOffset.TryParseExact(serverTime, new[] { "yyyy-MM-dd'T'HH:mm:sszzz", "yyyy-MM-dd HH:mm:ss" }, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out _))
            throw new InvalidDataException("Game login returned an invalid server time.");
        return new GameLoginData(identity.UserId, identity.Uuid, serverTime!);
    }

    private HttpRequestMessage Authenticated(HttpMethod method, string path, object? payload = null)
    {
        var identity = Get();
        var request = new HttpRequestMessage(method, path);
        if (payload is not null) request.Content = JsonContent.Create(payload);
        request.Headers.Add("x-olg-session", identity.Token);
        request.Headers.Add("api-token", identity.ApiToken);
        return request;
    }

    private async Task<SessionData> CreateAsync()
    {
        using var response = await client.PostAsJsonAsync("/local/login", new { profile }).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
        var root = document.RootElement;
        ValidateEnvelope(root);
        var contents = root.GetProperty("contents");
        var identity = new SessionData(contents.GetProperty("user_id").GetInt64(),
            contents.GetProperty("uuid").GetString() ?? "", contents.GetProperty("token").GetString() ?? "",
            root.GetProperty("api_token").GetString() ?? "");
        if (identity.UserId <= 0 || !Guid.TryParse(identity.Uuid, out _)
            || identity.Token.Length is < 16 or > 512 || identity.ApiToken.Length is < 16 or > 512
            || contents.GetProperty("token_status").GetInt32() != 0)
            throw new InvalidDataException("Local bootstrap returned an invalid identity.");
        return identity;
    }

    private static void ValidateEnvelope(JsonElement root)
    {
        if (root.GetProperty("status").GetString() != "success" || root.GetProperty("errors").GetProperty("code").GetInt32() != 0)
            throw new InvalidDataException("Local server returned an unsuccessful envelope.");
    }

    public void Dispose() => client.Dispose();
}

internal sealed record SessionData(long UserId, string Uuid, string Token, string ApiToken);
internal sealed record GameLoginData(long UserId, string Uuid, string ServerTime);
