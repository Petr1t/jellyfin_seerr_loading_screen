using System;
using System.Collections.Generic;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// jellyfin_seerr_loading_screen — surfaces Sonarr/Radarr pending downloads
/// as virtual Jellyfin library items with live progress.
/// </summary>
public class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
{
    public Plugin(IApplicationPaths appPaths, IXmlSerializer xmlSerializer)
        : base(appPaths, xmlSerializer)
    {
        Instance = this;
    }

    public override string Name => "Seerr Loading Screen";

    public override Guid Id => Guid.Parse("4f2c0e3a-9b4d-4f7c-9a31-2d6e8f1b5c0a");

    public override string Description =>
        "Show Sonarr/Radarr pending downloads as Jellyfin library items with live progress.";

    public static Plugin? Instance { get; private set; }

    public IEnumerable<PluginPageInfo> GetPages()
    {
        return new[]
        {
            new PluginPageInfo
            {
                Name = Name,
                EmbeddedResourcePath = $"{GetType().Namespace}.Configuration.configPage.html"
            }
        };
    }
}
