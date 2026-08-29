self.addEventListener('push', (event) => {
  let payload = {title: 'Agency Calendar', body: 'Vous avez une nouvelle notification.', url: '/notifications/'};
  if (event.data) {
    try { payload = {...payload, ...event.data.json()}; } catch (_error) { payload.body = event.data.text(); }
  }
  event.waitUntil(self.registration.showNotification(payload.title, {
    body: payload.body,
    tag: payload.tag || 'agency-calendar',
    data: {url: payload.url || '/notifications/'},
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = new URL(event.notification.data?.url || '/notifications/', self.location.origin).href;
  event.waitUntil(
    clients.matchAll({type: 'window', includeUncontrolled: true}).then((windows) => {
      const existing = windows.find((client) => client.url === targetUrl);
      return existing ? existing.focus() : clients.openWindow(targetUrl);
    })
  );
});
