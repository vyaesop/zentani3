"""Small request/response middlewares that need no third-party packages."""
from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Attach the Content-Security-Policy header from settings to HTML responses.

    Set CSP_REPORT_ONLY=true to emit the report-only variant while trialling a
    stricter policy. Responses that already carry a CSP header are left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = (getattr(settings, "CONTENT_SECURITY_POLICY", "") or "").strip()
        self.header_name = (
            "Content-Security-Policy-Report-Only"
            if getattr(settings, "CSP_REPORT_ONLY", False)
            else "Content-Security-Policy"
        )

    def __call__(self, request):
        response = self.get_response(request)
        if not self.policy:
            return response
        if "Content-Security-Policy" in response or "Content-Security-Policy-Report-Only" in response:
            return response
        content_type = response.get("Content-Type", "")
        if content_type.startswith("text/html"):
            response[self.header_name] = self.policy
        return response
