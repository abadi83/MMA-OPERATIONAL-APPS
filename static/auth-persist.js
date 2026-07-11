// Save auth token from URL to localStorage
(function() {
    var url = new URL(window.location.href);
    var token = url.searchParams.get('auth');
    if (token) {
        localStorage.setItem('iscan_auth_token', token);
        // Clean URL
        url.searchParams.delete('auth');
        window.history.replaceState({}, '', url.toString());
    }
    // On page load, if logged out but we have stored token, redirect with it
    var stored = localStorage.getItem('iscan_auth_token');
    if (stored && !token && !document.cookie.includes('iscan_auth')) {
        url.searchParams.set('auth', stored);
        window.location.replace(url.toString());
    }
})();
