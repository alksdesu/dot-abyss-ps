using System.Text;
using System.Text.Json;
using DotAbyss.Local.Pc;

internal static class EventBackgroundChecks
{
    internal static void Run()
    {
        var checks = 0;
        void Check(bool condition, string description)
        {
            if (!condition) throw new InvalidOperationException(description);
            checks++;
        }
        void Reject(string json)
        {
            try { EventBackgroundPolicy.Parse(Encoding.UTF8.GetBytes(json)); }
            catch (Exception error) when (error is InvalidDataException or JsonException) { checks++; return; }
            throw new InvalidOperationException("Invalid background policy was accepted.");
        }
        var revision = "assets-" + new string('a', 64);
        var payload = JsonSerializer.SerializeToUtf8Bytes(new {
            asset_revision = revision,
            backgrounds = new[] {
                new { id = "abg11101a", image_available = true },
                new { id = "functionbg012", image_available = true },
                new { id = "missing_image", image_available = false },
            }
        });
        var policy = EventBackgroundPolicy.Parse(payload);
        Check(policy.AssetRevision == revision && policy.Count == 3, "The policy retains its asset binding.");
        Check(policy.TryGet("abg11101a", out var image) && image == "Assets/Project/LazyAssets/General/UI/BG/Novel/abg11101a.png", "Known background uses the matching image.");
        Check(policy.TryGet("Functionbg012", out image) && image!.EndsWith("/Functionbg012.png"), "Native key casing is preserved.");
        Check(policy.TryGet("missing_image", out image) && image is null, "Missing images use the neutral background.");
        Check(!policy.TryGet("available_original", out image) && image is null, "Existing backgrounds keep native loading.");
        foreach (var identifier in new string?[] { null, "", "../abg11101a", "abg11101a/extra", "abg11101a\n" })
            Check(!policy.TryGet(identifier, out image) && image is null, "Unknown identifiers cannot build resource paths.");
        Check(!EventBackgroundPolicy.Empty.TryGet("abg11101a", out _), "Older servers preserve native behavior.");
        var empty = EventBackgroundPolicy.Parse(Encoding.UTF8.GetBytes("{\"asset_revision\":null,\"backgrounds\":[]}"));
        Check(empty.Count == 0, "No resource dataset permits an empty policy.");
        var entry = "{\"id\":\"abg11101a\",\"image_available\":true}";
        string Document(string entries) => "{\"asset_revision\":\"" + revision + "\",\"backgrounds\":" + entries + "}";
        foreach (var invalid in new[] { "", "null", "[]", "{}", "{\"asset_revision\":null,\"backgrounds\":[],\"unknown\":0}",
                    "{\"asset_revision\":null,\"backgrounds\":[" + entry + "]}",
                    Document("null"), Document("[" + entry + "," + entry + "]"),
                    Document("[{\"id\":\"../asset\",\"image_available\":true}]"),
                    Document("[{\"id\":\"asset\",\"image_available\":1}]"),
                    Document("[{\"id\":\"asset\",\"id\":\"other\",\"image_available\":true}]"),
                    Document("[" + string.Join(",", Enumerable.Repeat(entry, 257)) + "]"),
                    new string(' ', 65537) }) Reject(invalid);
        Check(new LocalOptions().EnableMissingEventBackgrounds, "Missing background compatibility is enabled by default.");
        Console.WriteLine($"Event background policy: {checks} checks passed.");
    }
}
