using Absf;
using Cysharp.Threading.Tasks;
using Il2CppInterop.Runtime;
using Project;
using Project.Master;
using Project.Master.NoaMessagePack;
using Project.Outgame.Event;
using UnityEngine;
using UnityEngine.UI;
using GameCancellationSource = Il2CppSystem.Threading.CancellationTokenSource;
using UnityObject = UnityEngine.Object;

namespace DotAbyss.Local.Pc;

internal static class EventBackgroundPatches
{
    private static EventBackgroundPolicy policy = EventBackgroundPolicy.Empty;
    private static readonly Dictionary<IntPtr, Background> backgrounds = new();

    internal static void Install(Plugin.AddHook add)
    {
        if (!Plugin.Options.EnableMissingEventBackgrounds) return;
        policy = Plugin.Session.GetEventBackgroundPolicy();
        add(typeof(EventBgController), "UpdateViewAsync", new[] { typeof(MEvents) }, typeof(EventBackgroundPatches), nameof(Update));
        add(typeof(EventBgController), "OnDestroy", Type.EmptyTypes, typeof(EventBackgroundPatches), nameof(Destroy));
        Plugin.Info("Missing event background compatibility ready: " + policy.Count + " backgrounds.");
    }

    internal static bool Update(EventBgController __instance, MEvents __0, ref UniTask __result)
    {
        if (!Plugin.Active || !__instance || __0 is null) return true;
        string? identifier;
        try { identifier = FindBackground(__0.id); }
        catch (Exception error)
        {
            Plugin.Info("Event background definition unavailable (" + error.GetType().Name + ").");
            return true;
        }
        if (!policy.TryGet(identifier, out var imageKey))
        {
            Release(__instance);
            return true;
        }
        if (backgrounds.TryGetValue(__instance.Pointer, out var existing))
        {
            if (existing.Identifier == identifier && existing.Root)
            {
                __result = existing.Completion.Task;
                return false;
            }
            Release(__instance);
        }
        if (__instance._bg) return true;
        Background? background = null;
        try
        {
            background = Create(__instance, identifier!);
            backgrounds.Add(__instance.Pointer, background);
            __instance._bg = background.Root;
            __result = background.Completion.Task;
            if (imageKey is null) background.Completion.TrySetResult();
            else LoadImage(background, imageKey);
            Plugin.Info("Using local event background compatibility: " + identifier + ", image=" + (imageKey is not null));
        }
        catch (Exception error)
        {
            if (background is not null)
            {
                background.Completion.TrySetResult();
                __result = background.Completion.Task;
            }
            else __result = UniTask.CompletedTask;
            Plugin.Info("Optional event background could not be created (" + error.GetType().Name + ").");
        }
        return false;
    }

    private static string? FindBackground(long eventId)
    {
        var entries = Engine.Get<MasterDataStore>()?.GetCache<MEventAssets>();
        if (entries is null) return null;
        foreach (var entry in entries)
            if (entry.m_event_id == eventId) return entry.bg_asset_id;
        return null;
    }

    private static Background Create(EventBgController owner, string identifier)
    {
        if (!owner._bgRoot) throw new InvalidOperationException("Event background root is unavailable.");
        var root = new GameObject("LocalEventBackground-" + identifier, new[] { Il2CppType.Of<RectTransform>() });
        try
        {
            Stretch(root, owner._bgRoot);
            root.transform.SetAsFirstSibling();
            var backing = root.AddComponent<Image>();
            backing.raycastTarget = false;
            backing.color = new Color(0.12f, 0.10f, 0.18f, 1f);
            var picture = new GameObject("Image", new[] { Il2CppType.Of<RectTransform>() });
            Stretch(picture, root.transform);
            var image = picture.AddComponent<Image>();
            image.raycastTarget = false;
            image.color = Color.clear;
            return new Background(owner, identifier, root, image);
        }
        catch
        {
            UnityObject.Destroy(root);
            throw;
        }
    }

    private static void Stretch(GameObject target, Transform parent)
    {
        var rectangle = target.GetComponent<RectTransform>();
        rectangle.SetParent(parent, false);
        rectangle.anchorMin = Vector2.zero;
        rectangle.anchorMax = Vector2.one;
        rectangle.offsetMin = Vector2.zero;
        rectangle.offsetMax = Vector2.zero;
        rectangle.localScale = Vector3.one;
    }

    private static void LoadImage(Background background, string key)
    {
        var awaiter = Engine.Get<AssetDataStore>().LoadAsync<Sprite>(key, CacheType.Scene, background.Cancellation.Token).GetAwaiter();
        void Finish()
        {
            try
            {
                var handle = awaiter.GetResult();
                if (!Current(background)) return;
                var sprite = handle?.Asset;
                if (sprite is null || !sprite || sprite.rect.width <= 0 || sprite.rect.height <= 0)
                    throw new InvalidDataException("Event background image is unavailable.");
                background.Image.sprite = sprite;
                background.Image.color = Color.white;
                var fitter = background.Image.gameObject.AddComponent<AspectRatioFitter>();
                fitter.aspectRatio = sprite.rect.width / sprite.rect.height;
                fitter.aspectMode = AspectRatioFitter.AspectMode.EnvelopeParent;
            }
            catch (Exception error)
            {
                if (Current(background))
                    Plugin.Info("Using neutral event background for " + background.Identifier + " (" + error.GetType().Name + ").");
            }
            finally
            {
                background.Completion.TrySetResult();
            }
        }
        if (awaiter.IsCompleted) Finish();
        else awaiter.OnCompleted((Il2CppSystem.Action)(Action)Finish);
    }

    private static bool Current(Background background) => background.Owner && background.Root && background.Image
        && backgrounds.TryGetValue(background.Owner.Pointer, out var current) && ReferenceEquals(current, background);

    internal static void Destroy(EventBgController __instance) => Release(__instance);

    private static void Release(EventBgController owner)
    {
        if (owner is null || !backgrounds.Remove(owner.Pointer, out var background)) return;
        try
        {
            background.Completion.TrySetCanceled(background.Cancellation.Token);
            background.Cancellation.Cancel();
        }
        catch (Exception error) { Plugin.Info("Event background cancellation failed (" + error.GetType().Name + ")."); }
        finally
        {
            background.Cancellation.Dispose();
            if (owner && owner._bg == background.Root) owner._bg = null;
            if (background.Root) UnityObject.Destroy(background.Root);
        }
    }

    private sealed class Background
    {
        internal EventBgController Owner { get; }
        internal string Identifier { get; }
        internal GameObject Root { get; }
        internal Image Image { get; }
        internal UniTaskCompletionSource Completion { get; } = new();
        internal GameCancellationSource Cancellation { get; } = new();

        internal Background(EventBgController owner, string identifier, GameObject root, Image image)
        {
            Owner = owner;
            Identifier = identifier;
            Root = root;
            Image = image;
        }
    }
}
