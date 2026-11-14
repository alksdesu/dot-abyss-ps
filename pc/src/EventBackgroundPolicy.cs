using System.Text.Json;
using System.Text.RegularExpressions;

namespace DotAbyss.Local.Pc;

internal sealed class EventBackgroundPolicy
{
    private readonly Dictionary<string, bool> backgrounds;
    internal static EventBackgroundPolicy Empty { get; } = new(null, new(StringComparer.OrdinalIgnoreCase));
    internal string? AssetRevision { get; }
    internal int Count => backgrounds.Count;

    private EventBackgroundPolicy(string? revision, Dictionary<string, bool> entries)
    {
        AssetRevision = revision;
        backgrounds = entries;
    }

    internal bool TryGet(string? identifier, out string? imageKey)
    {
        imageKey = null;
        if (identifier is null || !Regex.IsMatch(identifier, "\\A[A-Za-z0-9_]{1,64}\\z")
            || !backgrounds.TryGetValue(identifier, out var imageAvailable)) return false;
        if (imageAvailable) imageKey = "Assets/Project/LazyAssets/General/UI/BG/Novel/" + identifier + ".png";
        return true;
    }

    internal static EventBackgroundPolicy Parse(byte[] payload)
    {
        if (payload.Length is 0 or > 65536) throw new InvalidDataException("Invalid event background response size.");
        using var document = JsonDocument.Parse(payload);
        var root = document.RootElement;
        Fields(root, "asset_revision", "backgrounds");
        var revision = root.GetProperty("asset_revision");
        var entries = root.GetProperty("backgrounds");
        if (entries.ValueKind != JsonValueKind.Array || entries.GetArrayLength() > 256)
            throw new InvalidDataException("Invalid event background list.");
        string? assetRevision = null;
        if (revision.ValueKind != JsonValueKind.Null)
        {
            if (revision.ValueKind != JsonValueKind.String
                || !Regex.IsMatch(revision.GetString()!, "\\Aassets-[a-f0-9]{64}\\z"))
                throw new InvalidDataException("Invalid event background asset revision.");
            assetRevision = revision.GetString();
        }
        if (assetRevision is null && entries.GetArrayLength() != 0)
            throw new InvalidDataException("Event background entries require an asset revision.");
        var values = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries.EnumerateArray())
        {
            Fields(entry, "id", "image_available");
            var identifier = entry.GetProperty("id");
            var available = entry.GetProperty("image_available");
            if (identifier.ValueKind != JsonValueKind.String
                || !Regex.IsMatch(identifier.GetString()!, "\\A[A-Za-z0-9_]{1,64}\\z")
                || available.ValueKind is not (JsonValueKind.True or JsonValueKind.False)
                || !values.TryAdd(identifier.GetString()!, available.GetBoolean()))
                throw new InvalidDataException("Invalid or repeated event background entry.");
        }
        return new EventBackgroundPolicy(assetRevision, values);
    }

    private static void Fields(JsonElement value, params string[] names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Expected an event background object.");
        var fields = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!fields.Add(property.Name) || !names.Contains(property.Name, StringComparer.Ordinal))
                throw new InvalidDataException("Unknown or repeated event background field.");
        if (fields.Count != names.Length) throw new InvalidDataException("Missing event background field.");
    }
}
