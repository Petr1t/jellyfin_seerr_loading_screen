using MediaBrowser.Model.Plugins;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Plugin configuration. Persists to plugins/configurations/SeerrLoadingScreen.xml.
/// </summary>
public class PluginConfiguration : BasePluginConfiguration
{
    /// <summary>Daemon base URL, e.g. http://localhost:7000.</summary>
    public string DaemonUrl { get; set; } = "http://localhost:7000";

    /// <summary>Refresh interval in seconds. Min 10, max 600.</summary>
    public int RefreshIntervalSeconds { get; set; } = 30;

    /// <summary>If true, all users see all pending items. If false, filter by current user via Jellyseerr mapping.</summary>
    public bool ShowAllUsers { get; set; } = true;

    /// <summary>Display name of the virtual library that hosts pending items.</summary>
    public string VirtualLibraryName { get; set; } = "📥 Coming Soon";

    /// <summary>If true, hide items that have completed (vs showing them with READY badge for 5min).</summary>
    public bool HideCompleted { get; set; } = false;
}
