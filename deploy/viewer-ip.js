// CloudFront Function (viewer request), platform stage 8.2. Paste into CloudFront → Functions (runtime 2.0) and
// attach it to the distribution's behaviours. Writes the visitor's address into X-Viewer-IP, replacing any value
// the visitor sent; the backend reads it when auth.client_ip_header = X-Viewer-IP.
function handler(event) {
    var request = event.request;
    request.headers['x-viewer-ip'] = { value: event.viewer.ip };
    return request;
}
