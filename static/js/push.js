const pushPanel = document.querySelector('[data-push-panel]');

if (pushPanel) {
  const button = pushPanel.querySelector('[data-push-toggle]');
  const status = pushPanel.querySelector('[data-push-status]');
  const publicKey = pushPanel.dataset.publicKey;
  let activeSubscription = null;

  const csrfToken = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
  const publicKeyBytes = (value) => {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map((character) => character.charCodeAt(0)));
  };
  const render = (enabled, message) => {
    button.textContent = enabled ? 'Désactiver les notifications navigateur' : 'Activer les notifications navigateur';
    button.dataset.enabled = enabled ? 'true' : 'false';
    status.textContent = message;
  };
  const saveSubscription = (subscription) => fetch('/api/push-subscriptions/', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
    body: JSON.stringify(subscription.toJSON()),
  });

  const initialize = async () => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      button.disabled = true;
      status.textContent = 'Ce navigateur ne prend pas en charge les notifications Web Push.';
      return;
    }
    if (!publicKey) {
      button.disabled = true;
      status.textContent = 'Les notifications navigateur ne sont pas encore configurées.';
      return;
    }
    const registration = await navigator.serviceWorker.register('/service-worker.js', {scope: '/'});
    activeSubscription = await registration.pushManager.getSubscription();
    render(Boolean(activeSubscription), activeSubscription ? 'Notifications navigateur actives.' : 'Notifications navigateur désactivées.');
  };

  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      if (activeSubscription) {
        await fetch('/api/push-subscriptions/', {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
          body: JSON.stringify({endpoint: activeSubscription.endpoint}),
        });
        await activeSubscription.unsubscribe();
        activeSubscription = null;
        render(false, 'Notifications navigateur désactivées.');
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        render(false, 'Autorisation refusée par le navigateur.');
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      activeSubscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: publicKeyBytes(publicKey),
      });
      const response = await saveSubscription(activeSubscription);
      if (!response.ok) throw new Error('subscription_save_failed');
      render(true, 'Notifications navigateur actives.');
    } catch (_error) {
      status.textContent = 'Impossible de modifier les notifications. Réessayez.';
    } finally {
      button.disabled = false;
    }
  });

  initialize().catch(() => {
    button.disabled = true;
    status.textContent = 'Impossible d’initialiser les notifications navigateur.';
  });
}
