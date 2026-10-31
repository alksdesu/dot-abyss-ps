using System.Security.Cryptography;

namespace DotAbyss.Local.Pc;

internal static class ClientIdentity
{
    internal const string ApplicationVersion = ClientBuildProfile.ApplicationVersion;
    internal const string MetadataHash = ClientBuildProfile.MetadataHash;
    internal const string NativeHash = ClientBuildProfile.NativeHash;
    internal const string PreparedSettingsHash = ClientBuildProfile.PreparedSettingsHash;
    internal const string SchemaHash = ClientBuildProfile.SchemaHash;

    internal static void VerifyFiles(string dataPath)
    {
        Check(Path.Combine(dataPath, "il2cpp_data", "Metadata", "global-metadata.dat"), MetadataHash);
        Check(Path.Combine(Path.GetDirectoryName(dataPath)!, "GameAssembly.dll"), NativeHash);
        VerifySettings(dataPath);
    }

    internal static void VerifySettings(string dataPath) => Check(Path.Combine(dataPath, "globalgamemanagers"), PreparedSettingsHash);

    private static void Check(string path, string expected)
    {
        using var input = File.OpenRead(path);
        using var digest = SHA256.Create();
        var actual = Convert.ToHexString(digest.ComputeHash(input)).ToLowerInvariant();
        if (actual != expected) throw new InvalidDataException("Client fingerprint does not match the supported PC build.");
    }
}
