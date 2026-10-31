using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using DotAbyss.Local.Pc;

internal static class ContentBindingChecks
{
    internal static int Run(bool writeResult = true)
    {
        var checks = 0;
        void Check(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
            checks++;
        }
        void Reject(Action action, string message)
        {
            try { action(); }
            catch (Exception error) when (error is InvalidDataException or JsonException or HttpRequestException)
            { checks++; return; }
            throw new InvalidOperationException(message);
        }

        var options = new LocalOptions { ExpectedPersistentPath = Path.GetFullPath("local-profile") };
        Check(options.ExpectedCompany == ClientBuildProfile.IdentityCompany && options.ExpectedProduct == ClientBuildProfile.IdentityProduct,
            "The selected build supplies the isolated client identity.");
        Check(options.Validate().IsLoopback, "The generated isolated identity is accepted.");
        Reject(() => (options with { ExpectedCompany = ClientBuildProfile.IdentityCompany + "-other" }).Validate(), "A different isolated company was accepted.");
        Reject(() => (options with { ExpectedProduct = ClientBuildProfile.IdentityProduct + "-other" }).Validate(), "A different isolated product was accepted.");

        foreach (var seed in new[] { 'a', 'b' })
        {
            using var snapshot = JsonDocument.Parse(Snapshot(seed).ToJsonString());
            var binding = LocalSession.VerifyBinding(snapshot.RootElement);
            Check(binding.MasterRevision.StartsWith("local-" + new string(seed, 16), StringComparison.Ordinal),
                "A supported structure accepts independently bound content snapshots.");
            binding.VerifyCatalogHash(HashPayload(seed));
            checks++;
            using var handler = new BindingHandler(Snapshot(seed), HashPayload(seed));
            using var session = Session(handler);
            session.VerifyServer();
            Check(handler.DiagnosticsRequests == 1 && handler.HashRequests == 1, "Startup verifies one consistent content snapshot.");
        }

        var failures = new (string Name, Action<JsonObject> Change)[]
        {
            ("package", value => value["master"]!["client"]!["package"] = "other-client"),
            ("version", value => value["master"]!["client"]!["version"] = "unsupported"),
            ("metadata", value => value["master"]!["client"]!["metadata_sha256"] = new string('c', 64)),
            ("master digest", value => value["master"]!["sha256"] = "not-a-digest"),
            ("asset master digest", value => value["assets"]!["active"]!["master"]!["sha256"] = new string('b', 64)),
            ("master revision", value => value["master"]!["revision"] = "local-unbound"),
            ("asset master revision", value => value["assets"]!["active"]!["master"]!["revision"] = "local-unbound"),
            ("asset client", value => value["assets"]!["active"]!["master"]!["client"]!["package"] = "other-client"),
            ("asset schema", value => value["assets"]!["active"]!["master"]!["schema_sha256"] = new string('b', 64)),
            ("unsupported shared schema", value =>
            {
                value["master"]!["schema_sha256"] = new string('b', 64);
                value["assets"]!["active"]!["master"]!["schema_sha256"] = new string('b', 64);
                value["master"]!["revision"] = "local-" + new string('a', 16) + "-" + new string('b', 12);
                value["assets"]!["active"]!["master"]!["revision"] = value["master"]!["revision"]!.DeepClone();
            }),
            ("asset revision", value => value["assets"]!["active"]!["revision"] = "assets-unbound"),
            ("namespace", value => value["assets"]!["active"]!["prefix"] = "resources/other"),
            ("catalog unavailable", value => value["assets"]!["active"]!["catalog_served"] = false),
            ("asset error", value => value["assets"]!["error"] = "invalid binding"),
            ("state disabled", value => value["local_state"]!["enabled"] = false),
            ("state error", value => value["local_state"]!["error"] = "invalid schema"),
            ("missing catalog", value => value["assets"]!["active"]!.AsObject().Remove("catalog")),
            ("missing hash", value => value["assets"]!["active"]!.AsObject().Remove("catalog_hash")),
            ("missing hash value", value => value["assets"]!["active"]!.AsObject().Remove("catalog_hash_value")),
            ("catalog path", value => value["assets"]!["active"]!["catalog"]!["relative_path"] = "../catalog.bin"),
            ("hash path", value => value["assets"]!["active"]!["catalog_hash"]!["relative_path"] = "https://outside.example/hash"),
            ("empty catalog", value => value["assets"]!["active"]!["catalog"]!["bytes"] = 0),
            ("oversized catalog", value => value["assets"]!["active"]!["catalog"]!["bytes"] = ContentBinding.MaxCatalogBytes + 1),
            ("invalid catalog size", value => value["assets"]!["active"]!["catalog"]!["bytes"] = "large"),
            ("invalid catalog digest", value => value["assets"]!["active"]!["catalog"]!["sha256"] = "changed"),
            ("oversized hash", value => value["assets"]!["active"]!["catalog_hash"]!["bytes"] = ContentBinding.MaxHashBytes + 1),
            ("empty hash", value => value["assets"]!["active"]!["catalog_hash"]!["bytes"] = 0),
            ("invalid hash digest", value => value["assets"]!["active"]!["catalog_hash"]!["sha256"] = new string('z', 64)),
            ("invalid hash value", value => value["assets"]!["active"]!["catalog_hash_value"] = new string('g', 32)),
        };
        foreach (var failure in failures)
        {
            var value = Snapshot();
            failure.Change(value);
            using var document = JsonDocument.Parse(value.ToJsonString());
            Reject(() => LocalSession.VerifyBinding(document.RootElement), "Invalid binding accepted: " + failure.Name);
        }
        foreach (var invalid in new[] { "{}", "null", "[]", Snapshot().ToJsonString().Replace("\"master\":", "\"master\":{},\"master\":", StringComparison.Ordinal) })
        {
            using var document = JsonDocument.Parse(invalid);
            Reject(() => LocalSession.VerifyBinding(document.RootElement), "Missing or duplicate binding members accepted.");
        }

        using (var document = JsonDocument.Parse(Snapshot().ToJsonString()))
        {
            var binding = LocalSession.VerifyBinding(document.RootElement);
            Reject(() => binding.VerifyCatalogHash(Encoding.ASCII.GetBytes(new string('b', 32) + "\n")), "Altered hash payload accepted.");
            Reject(() => binding.VerifyCatalogHash(HashPayload('a')[..16]), "Truncated hash payload accepted.");
            var changedValue = Snapshot();
            changedValue["assets"]!["active"]!["catalog_hash_value"] = new string('b', 32);
            using var changed = JsonDocument.Parse(changedValue.ToJsonString());
            var changedBinding = LocalSession.VerifyBinding(changed.RootElement);
            Reject(() => changedBinding.VerifyCatalogHash(HashPayload('a')), "Unrelated catalog hash value accepted.");
        }

        foreach (var failure in new[] { "revision", "missing-revision", "duplicate-revision", "length", "payload", "truncated", "oversized", "http" })
        {
            using var handler = new BindingHandler(Snapshot(), HashPayload('a')) { Failure = failure };
            using var session = Session(handler);
            Reject(session.VerifyServer, "Invalid HTTP content snapshot accepted: " + failure);
            Check(handler.DiagnosticsRequests == 1 && handler.HashRequests == 1, "A failed check cannot silently mix snapshots.");
            if (failure == "oversized") Check(handler.StreamBytesRead == HashPayload('a').Length + 1, "Unknown-length content is read only to its bound.");
        }
        using (var handler = new BindingHandler(Snapshot(), HashPayload('a')) { UnknownLength = true })
        using (var session = Session(handler))
        {
            session.VerifyServer();
            Check(handler.StreamBytesRead == HashPayload('a').Length, "Bounded reads accept valid chunked hash responses.");
        }
        if (writeResult) Console.WriteLine($"Content binding: {checks} checks passed.");
        return checks;
    }

    private static LocalSession Session(HttpMessageHandler handler)
    {
        var options = new LocalOptions { ExpectedPersistentPath = Path.GetFullPath("local-profile") };
        return new LocalSession(options.Validate(), options, handler);
    }

    private static byte[] HashPayload(char seed) => Encoding.ASCII.GetBytes(new string(seed, 32) + "\n");
    private static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static JsonObject Snapshot(char seed = 'a')
    {
        var master = new
        {
            client = new { package = ClientBuildProfile.Package, version = ClientIdentity.ApplicationVersion, metadata_sha256 = ClientIdentity.MetadataHash },
            sha256 = new string(seed, 64), schema_sha256 = ClientIdentity.SchemaHash,
            revision = "local-" + new string(seed, 16) + "-" + ClientIdentity.SchemaHash[..12]
        };
        var hashPayload = HashPayload(seed);
        return JsonSerializer.SerializeToNode(new
        {
            master,
            assets = new
            {
                error = "",
                active = new
                {
                    revision = "assets-" + new string(seed, 64), master,
                    prefix = TransportPolicy.CatalogPrefix, catalog_served = true,
                    catalog = new { relative_path = TransportPolicy.CatalogPath.TrimStart('/'), sha256 = new string(seed, 64), bytes = 100 },
                    catalog_hash = new { relative_path = TransportPolicy.CatalogHashPath.TrimStart('/'), sha256 = Digest(hashPayload), bytes = hashPayload.Length },
                    catalog_hash_value = new string(seed, 32)
                }
            },
            local_state = new { enabled = true, error = "" }
        })!.AsObject();
    }

    private sealed class BindingHandler(JsonObject snapshot, byte[] payload) : HttpMessageHandler
    {
        public string Failure { get; init; } = "";
        public bool UnknownLength { get; init; }
        public int DiagnosticsRequests { get; private set; }
        public int HashRequests { get; private set; }
        public int StreamBytesRead => streamingContent?.BytesRead ?? 0;
        private UnknownLengthContent? streamingContent;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.RequestUri!.AbsolutePath == "/diagnostics")
            {
                DiagnosticsRequests++;
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(snapshot.ToJsonString()) });
            }
            if (request.RequestUri.AbsolutePath != TransportPolicy.CatalogHashPath || request.Method != HttpMethod.Get)
                throw new InvalidOperationException("Unexpected preflight request.");
            HashRequests++;
            var bytes = Failure switch
            {
                "payload" => HashPayload('b'),
                "truncated" => payload[..16],
                "oversized" => Enumerable.Repeat((byte)'a', 4096).ToArray(),
                _ => payload
            };
            HttpContent content = UnknownLength || Failure is "truncated" or "oversized"
                ? streamingContent = new UnknownLengthContent(bytes) : new ByteArrayContent(bytes);
            if (Failure == "length") content.Headers.ContentLength = payload.Length + 1;
            var response = new HttpResponseMessage(Failure == "http" ? HttpStatusCode.ServiceUnavailable : HttpStatusCode.OK) { Content = content };
            var revision = snapshot["assets"]!["active"]!["revision"]!.GetValue<string>();
            if (Failure != "missing-revision") response.Headers.Add("X-Asset-Revision", Failure == "revision" ? "assets-" + new string('b', 64) : revision);
            if (Failure == "duplicate-revision") response.Headers.Add("X-Asset-Revision", revision);
            return Task.FromResult(response);
        }
    }

    private sealed class UnknownLengthContent(byte[] bytes) : HttpContent
    {
        private readonly CountedStream stream = new(bytes);
        public int BytesRead => stream.BytesRead;
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream target, TransportContext? context) => target.WriteAsync(bytes).AsTask();
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(stream);
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(stream);
    }

    private sealed class CountedStream(byte[] bytes) : MemoryStream(bytes, writable: false)
    {
        public int BytesRead { get; private set; }
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            var count = await base.ReadAsync(buffer, cancellationToken);
            BytesRead += count;
            return count;
        }
    }
}
