using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Second channel, next to "Coming Soon": approved Jellyseerr requests for which
/// Sonarr/Radarr never found a release. They get their own shelf because they are
/// a different kind of thing — nothing is coming, the user has to act.
///
/// Everything but the name and the status filter is inherited from
/// <see cref="SeerrLoadingScreenChannel"/>; both instances keep their own
/// cache key, so they refresh independently.
/// </summary>
public class NotFoundChannel : SeerrLoadingScreenChannel
{
    public NotFoundChannel(DaemonClient daemon, ILogger<NotFoundChannel> log)
        : base(daemon, log)
    {
    }

    public override string Name =>
        Plugin.Instance?.Configuration.NotFoundLibraryName ?? "Leider nicht gefunden";

    public override string Description =>
        "Angefragte Titel, zu denen kein Release gefunden wurde.";

    protected override bool Includes(PendingItem p) => p.Status == "not_found";
}
