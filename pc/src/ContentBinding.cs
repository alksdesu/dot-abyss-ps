using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace DotAbyss.Local.Pc;

internal sealed record ContentAsset(string Path, string Sha256, int Bytes);

internal sealed record ContentBinding(string Revision, string MasterRevision, ContentAsset Catalog,
    ContentAsset CatalogHash, string CatalogHashValue)
{
    internal const int MaxCatalogBytes = 128 * 1024 * 1024;
    internal const int MaxHashBytes = 128;

    internal static ContentBinding Parse(JsonElement status)
    {
        try
        {
            var master = Member(status, "master");
            var assets = Member(status, "assets");
            var active = Member(assets, "active");
            var assetMaster = Member(active, "master");
            var local = Member(status, "local_state");
            var masterHash = Hex(master, "sha256", 64);
            var schemaHash = Hex(master, "schema_sha256", 64);
            var masterRevision = Text(master, "revision", 128);
            var assetRevision = Text(active, "revision", 128);
            if (!SupportedClient(Member(master, "client")) || schemaHash != ClientIdentity.SchemaHash
                || masterRevision != "local-" + masterHash[..16] + "-" + schemaHash[..12]
                || Text(assetMaster, "revision", 128) != masterRevision
                || Hex(assetMaster, "sha256", 64) != masterHash
                || Hex(assetMaster, "schema_sha256", 64) != schemaHash
                || !SupportedClient(Member(assetMaster, "client"))
                || !assetRevision.StartsWith("assets-", StringComparison.Ordinal) || !IsHex(assetRevision[7..], 64)
                || Text(active, "prefix", 512) != TransportPolicy.CatalogPrefix
                || !Member(active, "catalog_served").GetBoolean()
                || Text(assets, "error", 4096) != "" || !Member(local, "enabled").GetBoolean()
                || Text(local, "error", 4096) != "")
                throw new InvalidDataException("The local service master, assets and PC profile are not bound together.");
            return new ContentBinding(assetRevision, masterRevision,
                Asset(Member(active, "catalog"), TransportPolicy.CatalogPath, MaxCatalogBytes),
                Asset(Member(active, "catalog_hash"), TransportPolicy.CatalogHashPath, MaxHashBytes),
                Hex(active, "catalog_hash_value", 32));
        }
        catch (Exception error) when (error is KeyNotFoundException or InvalidOperationException or FormatException or OverflowException)
        {
            throw new InvalidDataException("The local service content binding is missing or invalid; update the service and adapter together.", error);
        }
    }

    internal void VerifyCatalogHash(ReadOnlySpan<byte> payload)
    {
        using var digest = SHA256.Create();
        if (payload.Length != CatalogHash.Bytes
            || Convert.ToHexString(digest.ComputeHash(payload.ToArray())).ToLowerInvariant() != CatalogHash.Sha256
            || Encoding.ASCII.GetString(payload).Trim() != CatalogHashValue)
            throw new InvalidDataException("The local catalog hash does not match its active content snapshot.");
    }

    private static ContentAsset Asset(JsonElement value, string expectedPath, int maximumBytes)
    {
        var path = Text(value, "relative_path", 512);
        var sha256 = Hex(value, "sha256", 64);
        var bytes = Member(value, "bytes").GetInt32();
        if ("/" + path != expectedPath || bytes <= 0 || bytes > maximumBytes)
            throw new InvalidDataException("The local catalog descriptor has an invalid path or size.");
        return new ContentAsset(expectedPath, sha256, bytes);
    }

    private static bool SupportedClient(JsonElement value) => Text(value, "package", 128) == ClientBuildProfile.Package
        && Text(value, "version", 128) == ClientIdentity.ApplicationVersion
        && Hex(value, "metadata_sha256", 64) == ClientIdentity.MetadataHash;

    private static JsonElement Member(JsonElement value, string name)
    {
        JsonElement result = default;
        var count = 0;
        foreach (var item in value.EnumerateObject())
            if (item.NameEquals(name)) { result = item.Value; count++; }
        if (count != 1) throw new InvalidDataException("The local content binding requires one " + name + " property.");
        return result;
    }

    private static string Text(JsonElement value, string name, int maximum)
    {
        var text = Member(value, name).GetString();
        if (text is null || text.Length > maximum)
            throw new InvalidDataException("The local content binding has an invalid " + name + " value.");
        return text;
    }

    private static string Hex(JsonElement value, string name, int length)
    {
        var text = Text(value, name, length);
        if (!IsHex(text, length)) throw new InvalidDataException("The local content binding has an invalid " + name + " digest.");
        return text;
    }

    private static bool IsHex(string value, int length) => value.Length == length
        && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
