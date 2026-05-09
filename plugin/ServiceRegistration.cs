using MediaBrowser.Controller;
using MediaBrowser.Controller.Channels;
using MediaBrowser.Controller.Plugins;
using Microsoft.Extensions.DependencyInjection;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Registers the DaemonClient and the Channel implementation with Jellyfin's DI
/// container. Jellyfin discovers channels via <c>IServiceProvider.GetServices&lt;IChannel&gt;()</c>,
/// so the channel must be registered as a DI service explicitly — there is no assembly scan.
/// </summary>
public class ServiceRegistration : IPluginServiceRegistrator
{
    public void RegisterServices(IServiceCollection services, IServerApplicationHost applicationHost)
    {
        services.AddHttpClient<DaemonClient>();
        services.AddSingleton<IChannel, SeerrLoadingScreenChannel>();
    }
}
