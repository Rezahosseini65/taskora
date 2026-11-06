from rest_framework.throttling import SimpleRateThrottle


class UserRegisterThrottle(SimpleRateThrottle):
    scope = "user_register_throttle"

    def get_cache_key(self, request, view):
        """
        Throttle registration requests based on client IP address.
        """
        ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class UserLoginThrottle(SimpleRateThrottle):
    scope = 'user_login_throttle'

    def get_cache_key(self, request, view):
        """
        Throttle login requests based on client IP address.
        """
        ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }