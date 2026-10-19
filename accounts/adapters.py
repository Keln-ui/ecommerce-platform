from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount


class CustomAccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        # Set default role if not set
        if not hasattr(user, 'role') or not user.role:
            user.role = user.Role.BUYER
        if commit:
            user.save()
        return user

    def populate_username(self, request, user):
        # Generate username from email since we don't use username field
        if not user.username:
            user.username = user.email.split('@')[0]
        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # If a user already exists with the same email, link the social account
        if sociallogin.is_existing:
            return

        user = sociallogin.user
        email = user.email

        if email:
            from accounts.models import User

            try:
                existing_user = User.objects.get(email=email)
                sociallogin.connect(request, existing_user)
            except User.DoesNotExist:
                # New user - set default role
                if not hasattr(user, 'role') or not user.role:
                    user.role = user.Role.BUYER
                # Set username from email
                if not user.username:
                    user.username = email.split('@')[0]

    def save_user(self, request, sociallogin, form=None):
        """
        Hook that fires after a user signs up via social account.
        This is called when a new user is created via Google OAuth.
        """
        user = super().save_user(request, sociallogin, form)
        
        # Ensure the user has a role set
        if not hasattr(user, 'role') or not user.role:
            user.role = user.Role.BUYER
            user.save(update_fields=['role'])
        
        return user
