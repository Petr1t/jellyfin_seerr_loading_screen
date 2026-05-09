using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Model.Tasks;
using Microsoft.Extensions.Logging;

using Jellyfin.Plugin.SeerrLoadingScreen.Services;

namespace Jellyfin.Plugin.SeerrLoadingScreen.ScheduledTasks;

/// <summary>
/// Periodic task: pulls the daemon's queue, syncs into Jellyfin's virtual library.
///
/// NOTE v0.2 skeleton: this currently logs the queue. Wiring into ILibraryManager
/// to create virtual BaseItem entries is the next milestone — see ROADMAP.md.
/// </summary>
public class RefreshTask : IScheduledTask
{
    private readonly DaemonClient _daemon;
    private readonly ILogger<RefreshTask> _log;

    public RefreshTask(DaemonClient daemon, ILogger<RefreshTask> log)
    {
        _daemon = daemon;
        _log = log;
    }

    public string Name => "Refresh Coming-Soon items";

    public string Key => "SeerrLoadingScreenRefresh";

    public string Description => "Polls the jslsd daemon for pending Sonarr/Radarr downloads.";

    public string Category => "Library";

    public async Task ExecuteAsync(IProgress<double> progress, CancellationToken ct)
    {
        progress.Report(0);
        var items = await _daemon.ListAsync(ct).ConfigureAwait(false);
        _log.LogInformation("Daemon returned {Count} pending item(s)", items.Length);

        // TODO v0.2 milestone: Create/update virtual BaseItem entries via ILibraryManager.
        // See https://github.com/jellyfin/jellyfin/blob/master/Emby.Server.Implementations/Library/LibraryManager.cs
        // for the AddVirtualFolder / RegisterItem API surface.

        progress.Report(100);
    }

    public IEnumerable<TaskTriggerInfo> GetDefaultTriggers()
    {
        var interval = Math.Max(
            10,
            Plugin.Instance?.Configuration.RefreshIntervalSeconds ?? 30
        );
        return new[]
        {
            new TaskTriggerInfo
            {
                Type = TaskTriggerInfo.TriggerInterval,
                IntervalTicks = TimeSpan.FromSeconds(interval).Ticks
            }
        };
    }
}
