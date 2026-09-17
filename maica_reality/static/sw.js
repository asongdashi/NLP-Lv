self.addEventListener('push', function(event) {
  let data = {};
  try { data = event.data.json(); } catch(e) {
    data = { title: 'Monika', body: event.data.text() };
  }
  const options = {
    body: data.body || '',
    icon: data.icon || '/static/icon.png',
    badge: data.badge || '/static/badge.png',
    data: data.data || { url: '/m' },
  };
  event.waitUntil(self.registration.showNotification(data.title || 'Monika', options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/m';
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(function(clientList) {
      for (let client of clientList) {
        if (client.url.includes(url) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
