# Google OAuth Setup Guide

To enable Google Sign-In for your marketplace, you need to set up Google OAuth credentials.

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API (or People API) for your project

## Step 2: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth client ID**
3. Configure the consent screen if prompted:
   - Choose **External** user type
   - Fill in the required fields (app name, email, etc.)
   - Add your email as a test user
4. For the OAuth client ID:
   - Application type: **Web application**
   - Name: MultiVendor Market (or your preferred name)
   - Authorized redirect URIs:
     - `http://127.0.0.1:8000/accounts/google/login/callback/` (for local development)
     - `http://localhost:8000/accounts/google/login/callback/` (alternative local)
     - `https://yourdomain.com/accounts/google/login/callback/` (for production)

## Step 3: Get Your Credentials

After creating the OAuth client, you'll receive:
- **Client ID** (looks like: `123456789-abcdef.apps.googleusercontent.com`)
- **Client Secret** (a random string)

## Step 4: Configure in Django Admin

1. Log in to your Django admin at `/admin/`
2. Go to **Sites** and ensure there's a site with `id=1` and the correct domain
3. Go to **Social Applications** > **Add social application**
4. Fill in:
   - **Provider**: Google
   - **Name**: Google (or any name you prefer)
   - **Client id**: Your Google Client ID
   - **Secret key**: Your Google Client Secret
   - **Key**: (leave empty)
5. Add your site to the **Sites** field (select the site with id=1)

## Step 5: Test the Integration

1. Visit `/login/` or `/register/`
2. Click the "Sign in with Google" or "Sign up with Google" button
3. You'll be redirected to Google's OAuth consent screen
4. After authorizing, you'll be redirected back to your app
5. A new user account will be created automatically (if you don't already have one with that email)

## Important Notes

- **For Local Development**: Use `http://127.0.0.1:8000` or `http://localhost:8000` in the authorized redirect URIs
- **For Production**: Use your actual domain with HTTPS
- **Email Matching**: If a user signs up with Google, it will try to match their email with existing accounts
- **Default Role**: New users signing up with Google will be assigned the BUYER role by default

## Troubleshooting

### "redirect_uri_mismatch" Error
- Make sure the redirect URI in Google Console exactly matches what Django generates
- Check that you're using the correct protocol (http vs https)

### "Invalid Client" Error
- Verify the Client ID and Secret are correct
- Make sure the social application is associated with the correct site

### No Button Showing
- Ensure django-allauth is properly installed
- Check that the Google provider is added to INSTALLED_APPS
- Verify the URL patterns include allauth URLs
