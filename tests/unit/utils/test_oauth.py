"""Tests for the OAuth utilities."""

import json
import time
import urllib.parse
from unittest.mock import MagicMock, patch

import requests

from mcp_atlassian.utils.oauth import (
    KEYRING_SERVICE_NAME,
    TOKEN_EXPIRY_MARGIN,
    BYOAccessTokenOAuthConfig,
    OAuthConfig,
    configure_oauth_session,
    get_oauth_config_from_env,
)


class TestOAuthConfig:
    """Tests for the OAuthConfig class."""

    def test_init_with_required_params(self):
        """Test initialization with required parameters."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        assert config.client_id == "test-client-id"
        assert config.client_secret == "test-client-secret"
        assert config.redirect_uri == "https://example.com/callback"
        assert config.scope == "read:jira-work write:jira-work"
        assert config.cloud_id is None
        assert config.refresh_token is None
        assert config.access_token is None
        assert config.expires_at is None

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            cloud_id="test-cloud-id",
            refresh_token="test-refresh-token",
            access_token="test-access-token",
            expires_at=time.time() + 3600,
        )
        assert config.client_id == "test-client-id"
        assert config.cloud_id == "test-cloud-id"
        assert config.access_token == "test-access-token"
        assert config.refresh_token == "test-refresh-token"
        assert config.expires_at is not None

    def test_is_token_expired_no_token(self):
        """Test is_token_expired when no token is set."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        assert config.is_token_expired is True

    def test_is_token_expired_token_expired(self):
        """Test is_token_expired when token is expired."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            access_token="test-access-token",
            expires_at=time.time() - 100,  # Expired 100 seconds ago
        )
        assert config.is_token_expired is True

    def test_is_token_expired_token_expiring_soon(self):
        """Test is_token_expired when token expires soon."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            access_token="test-access-token",
            expires_at=time.time() + (TOKEN_EXPIRY_MARGIN - 10),  # Expires soon
        )
        assert config.is_token_expired is True

    def test_is_token_expired_token_valid(self):
        """Test is_token_expired when token is valid."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            access_token="test-access-token",
            expires_at=time.time() + 3600,  # Expires in 1 hour
        )
        assert config.is_token_expired is False

    def test_get_authorization_url(self):
        """Test get_authorization_url method."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        url = config.get_authorization_url(state="test-state")

        # Parse the URL to check parameters properly
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        assert (
            parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path
            == "https://auth.atlassian.com/authorize"
        )
        assert query_params["client_id"] == ["test-client-id"]
        assert query_params["scope"] == ["read:jira-work write:jira-work"]
        assert query_params["redirect_uri"] == ["https://example.com/callback"]
        assert query_params["response_type"] == ["code"]
        assert query_params["state"] == ["test-state"]

    @patch("requests.post")
    def test_exchange_code_for_tokens_success(self, mock_post):
        """Test successful exchange_code_for_tokens."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_response

        # Mock cloud ID retrieval and token saving
        with patch.object(OAuthConfig, "_get_cloud_id") as mock_get_cloud_id:
            with patch.object(OAuthConfig, "_save_tokens") as mock_save_tokens:
                config = OAuthConfig(
                    client_id="test-client-id",
                    client_secret="test-client-secret",
                    redirect_uri="https://example.com/callback",
                    scope="read:jira-work write:jira-work",
                )
                result = config.exchange_code_for_tokens("test-code")

                # Check result
                assert result is True
                assert config.access_token == "new-access-token"
                assert config.refresh_token == "new-refresh-token"
                assert config.expires_at is not None

                # Verify calls
                mock_post.assert_called_once()
                mock_get_cloud_id.assert_called_once()
                mock_save_tokens.assert_called_once()

    @patch("requests.post")
    def test_exchange_code_for_tokens_failure(self, mock_post):
        """Test failed exchange_code_for_tokens."""
        mock_post.side_effect = Exception("API error")

        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        result = config.exchange_code_for_tokens("test-code")

        # Check result
        assert result is False
        assert config.access_token is None
        assert config.refresh_token is None

    @patch("requests.post")
    def test_refresh_access_token_success(self, mock_post):
        """Test successful refresh_access_token."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_response

        with patch.object(OAuthConfig, "_save_tokens") as mock_save_tokens:
            config = OAuthConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.com/callback",
                scope="read:jira-work write:jira-work",
                refresh_token="old-refresh-token",
            )
            result = config.refresh_access_token()

            # Check result
            assert result is True
            assert config.access_token == "new-access-token"
            assert config.refresh_token == "new-refresh-token"
            assert config.expires_at is not None

            # Verify calls
            mock_post.assert_called_once()
            mock_save_tokens.assert_called_once()

    def test_refresh_access_token_no_refresh_token(self):
        """Test refresh_access_token with no refresh token."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        result = config.refresh_access_token()

        # Check result
        assert result is False

    @patch("requests.post")
    def test_ensure_valid_token_already_valid(self, mock_post):
        """Test ensure_valid_token when token is already valid."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            access_token="test-access-token",
            expires_at=time.time() + 3600,  # Expires in 1 hour
        )
        result = config.ensure_valid_token()

        # Check result
        assert result is True
        # Should not have tried to refresh the token
        mock_post.assert_not_called()

    @patch.object(OAuthConfig, "refresh_access_token")
    def test_ensure_valid_token_needs_refresh_success(self, mock_refresh):
        """Test ensure_valid_token when token needs refreshing (success case)."""
        mock_refresh.return_value = True

        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            refresh_token="test-refresh-token",
            access_token="test-access-token",
            expires_at=time.time() - 100,  # Expired 100 seconds ago
        )
        result = config.ensure_valid_token()

        # Check result
        assert result is True
        mock_refresh.assert_called_once()

    @patch.object(OAuthConfig, "refresh_access_token")
    def test_ensure_valid_token_needs_refresh_failure(self, mock_refresh):
        """Test ensure_valid_token when token needs refreshing (failure case)."""
        mock_refresh.return_value = False

        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            refresh_token="test-refresh-token",
            access_token="test-access-token",
            expires_at=time.time() - 100,  # Expired 100 seconds ago
        )
        result = config.ensure_valid_token()

        # Check result
        assert result is False
        mock_refresh.assert_called_once()

    @patch("requests.get")
    def test_get_cloud_id_success(self, mock_get):
        """Test _get_cloud_id success case."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "test-cloud-id", "name": "Test Site"}]
        mock_get.return_value = mock_response

        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            access_token="test-access-token",
        )
        config._get_cloud_id()

        # Check result
        assert config.cloud_id == "test-cloud-id"
        mock_get.assert_called_once()
        headers = mock_get.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-access-token"

    @patch("requests.get")
    def test_get_cloud_id_no_access_token(self, mock_get):
        """Test _get_cloud_id with no access token."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        config._get_cloud_id()

        # Should not make API call without token
        mock_get.assert_not_called()
        assert config.cloud_id is None

    def test_get_keyring_username(self):
        """Test _get_keyring_username method."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
        )
        username = config._get_keyring_username()

        # Check the keyring username format
        assert username == "oauth-test-client-id"

    @patch("keyring.set_password")
    @patch.object(OAuthConfig, "_save_tokens_to_file")
    def test_save_tokens_keyring_success(self, mock_save_to_file, mock_set_password):
        """Test _save_tokens with successful keyring storage."""
        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            cloud_id="test-cloud-id",
            refresh_token="test-refresh-token",
            access_token="test-access-token",
            expires_at=1234567890,
        )
        config._save_tokens()

        # Verify keyring was used
        mock_set_password.assert_called_once()
        service_name = mock_set_password.call_args[0][0]
        username = mock_set_password.call_args[0][1]
        token_json = mock_set_password.call_args[0][2]

        assert service_name == KEYRING_SERVICE_NAME
        assert username == "oauth-test-client-id"
        assert "test-refresh-token" in token_json
        assert "test-access-token" in token_json

        # Verify file backup was created
        mock_save_to_file.assert_called_once()

    @patch("keyring.set_password")
    @patch.object(OAuthConfig, "_save_tokens_to_file")
    def test_save_tokens_keyring_failure(self, mock_save_to_file, mock_set_password):
        """Test _save_tokens with keyring failure fallback."""
        # Make keyring fail
        mock_set_password.side_effect = Exception("Keyring error")

        config = OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="https://example.com/callback",
            scope="read:jira-work write:jira-work",
            cloud_id="test-cloud-id",
            refresh_token="test-refresh-token",
            access_token="test-access-token",
            expires_at=1234567890,
        )
        config._save_tokens()

        # Verify keyring was attempted
        mock_set_password.assert_called_once()

        # Verify fallback to file was used
        mock_save_to_file.assert_called_once()

    @patch("pathlib.Path.mkdir")
    @patch("json.dump")
    def test_save_tokens_to_file(self, mock_dump, mock_mkdir):
        """Test _save_tokens_to_file method."""
        # Mock open
        mock_open = MagicMock()
        with patch("builtins.open", mock_open):
            config = OAuthConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.com/callback",
                scope="read:jira-work write:jira-work",
                cloud_id="test-cloud-id",
                refresh_token="test-refresh-token",
                access_token="test-access-token",
                expires_at=1234567890,
            )
            config._save_tokens_to_file()

            # Should create directory and save tokens
            mock_mkdir.assert_called_once()
            mock_open.assert_called_once()
            mock_dump.assert_called_once()

            # Check saved data
            saved_data = mock_dump.call_args[0][0]
            assert saved_data["refresh_token"] == "test-refresh-token"
            assert saved_data["access_token"] == "test-access-token"
            assert saved_data["expires_at"] == 1234567890
            assert saved_data["cloud_id"] == "test-cloud-id"

    @patch("keyring.get_password")
    @patch.object(OAuthConfig, "_load_tokens_from_file")
    def test_load_tokens_keyring_success(self, mock_load_from_file, mock_get_password):
        """Test load_tokens with successful keyring retrieval."""
        # Setup keyring to return token data
        token_data = {
            "refresh_token": "keyring-refresh-token",
            "access_token": "keyring-access-token",
            "expires_at": 1234567890,
            "cloud_id": "keyring-cloud-id",
        }
        mock_get_password.return_value = json.dumps(token_data)

        result = OAuthConfig.load_tokens("test-client-id")

        # Should have used keyring
        mock_get_password.assert_called_once_with(
            KEYRING_SERVICE_NAME, "oauth-test-client-id"
        )

        # Should not fall back to file
        mock_load_from_file.assert_not_called()

        # Check result contains keyring data
        assert result["refresh_token"] == "keyring-refresh-token"
        assert result["access_token"] == "keyring-access-token"
        assert result["expires_at"] == 1234567890
        assert result["cloud_id"] == "keyring-cloud-id"

    @patch("keyring.get_password")
    @patch.object(OAuthConfig, "_load_tokens_from_file")
    def test_load_tokens_keyring_failure(self, mock_load_from_file, mock_get_password):
        """Test load_tokens with keyring failure fallback."""
        # Make keyring fail
        mock_get_password.side_effect = Exception("Keyring error")

        # Setup file fallback to return token data
        file_token_data = {
            "refresh_token": "file-refresh-token",
            "access_token": "file-access-token",
            "expires_at": 9876543210,
            "cloud_id": "file-cloud-id",
        }
        mock_load_from_file.return_value = file_token_data

        result = OAuthConfig.load_tokens("test-client-id")

        # Should have tried keyring
        mock_get_password.assert_called_once()

        # Should have fallen back to file
        mock_load_from_file.assert_called_once_with("test-client-id")

        # Check result contains file data
        assert result["refresh_token"] == "file-refresh-token"
        assert result["access_token"] == "file-access-token"
        assert result["expires_at"] == 9876543210
        assert result["cloud_id"] == "file-cloud-id"

    @patch("keyring.get_password")
    @patch.object(OAuthConfig, "_load_tokens_from_file")
    def test_load_tokens_keyring_empty(self, mock_load_from_file, mock_get_password):
        """Test load_tokens with empty keyring result."""
        # Setup keyring to return None (no saved token)
        mock_get_password.return_value = None

        # Setup file fallback to return token data
        file_token_data = {
            "refresh_token": "file-refresh-token",
            "access_token": "file-access-token",
            "expires_at": 9876543210,
        }
        mock_load_from_file.return_value = file_token_data

        result = OAuthConfig.load_tokens("test-client-id")

        # Should have tried keyring
        mock_get_password.assert_called_once()

        # Should have fallen back to file
        mock_load_from_file.assert_called_once_with("test-client-id")

        # Check result contains file data
        assert result["refresh_token"] == "file-refresh-token"
        assert result["access_token"] == "file-access-token"
        assert result["expires_at"] == 9876543210

    @patch("pathlib.Path.exists")
    @patch("json.load")
    def test_load_tokens_from_file_success(self, mock_load, mock_exists):
        """Test _load_tokens_from_file success case."""
        mock_exists.return_value = True
        mock_load.return_value = {
            "refresh_token": "test-refresh-token",
            "access_token": "test-access-token",
            "expires_at": 1234567890,
            "cloud_id": "test-cloud-id",
        }

        # Mock open
        mock_open = MagicMock()
        with patch("builtins.open", mock_open):
            result = OAuthConfig._load_tokens_from_file("test-client-id")

            # Check result
            assert result["refresh_token"] == "test-refresh-token"
            assert result["access_token"] == "test-access-token"
            assert result["expires_at"] == 1234567890
            assert result["cloud_id"] == "test-cloud-id"

    @patch("pathlib.Path.exists")
    def test_load_tokens_from_file_not_found(self, mock_exists):
        """Test _load_tokens_from_file when file doesn't exist."""
        mock_exists.return_value = False

        result = OAuthConfig._load_tokens_from_file("test-client-id")

        # Should return empty dict
        assert result == {}

    @patch("os.getenv")
    def test_from_env_success(self, mock_getenv):
        """Test from_env success case."""
        # Mock environment variables
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_CLIENT_ID": "env-client-id",
            "ATLASSIAN_OAUTH_CLIENT_SECRET": "env-client-secret",
            "ATLASSIAN_OAUTH_REDIRECT_URI": "https://example.com/callback",
            "ATLASSIAN_OAUTH_SCOPE": "read:jira-work",
            "ATLASSIAN_OAUTH_CLOUD_ID": "env-cloud-id",
        }.get(key, default)

        # Mock token loading
        with patch.object(
            OAuthConfig,
            "load_tokens",
            return_value={
                "refresh_token": "loaded-refresh-token",
                "access_token": "loaded-access-token",
                "expires_at": 1234567890,
            },
        ):
            config = OAuthConfig.from_env()

            # Check result
            assert config is not None
            assert config.client_id == "env-client-id"
            assert config.client_secret == "env-client-secret"
            assert config.redirect_uri == "https://example.com/callback"
            assert config.scope == "read:jira-work"
            assert config.cloud_id == "env-cloud-id"
            assert config.refresh_token == "loaded-refresh-token"
            assert config.access_token == "loaded-access-token"
            assert config.expires_at == 1234567890

    @patch("os.getenv")
    def test_from_env_missing_required(self, mock_getenv):
        """Test from_env with missing required variables."""
        # Mock environment variables - missing some required ones
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_CLIENT_ID": "env-client-id",
            # Missing client secret
            "ATLASSIAN_OAUTH_REDIRECT_URI": "https://example.com/callback",
            # Missing scope
        }.get(key, default)

        config = OAuthConfig.from_env()

        # Should return None if required variables are missing
        assert config is None

    @patch("os.getenv")
    def test_from_env_minimal_oauth_enabled(self, mock_getenv):
        """Test from_env with minimal OAuth configuration (ATLASSIAN_OAUTH_ENABLE=true)."""
        # Mock environment variables - only ATLASSIAN_OAUTH_ENABLE is set
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_ENABLE": "true",
            "ATLASSIAN_OAUTH_CLOUD_ID": "cloud-id",  # Optional fallback
        }.get(key, default)

        config = OAuthConfig.from_env()

        # Should return minimal config when OAuth is enabled
        assert config is not None
        assert config.client_id == ""
        assert config.client_secret == ""
        assert config.redirect_uri == ""
        assert config.scope == ""
        assert config.cloud_id == "cloud-id"

    @patch("os.getenv")
    def test_from_env_minimal_oauth_disabled(self, mock_getenv):
        """Test from_env with minimal OAuth configuration disabled."""
        # Mock environment variables - ATLASSIAN_OAUTH_ENABLE is false
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_ENABLE": "false",
        }.get(key, default)

        config = OAuthConfig.from_env()

        # Should return None when OAuth is disabled
        assert config is None

    @patch("os.getenv")
    def test_from_env_full_oauth_takes_precedence(self, mock_getenv):
        """Test that full OAuth configuration takes precedence over minimal config."""
        # Mock environment variables - both full OAuth and ATLASSIAN_OAUTH_ENABLE
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_ENABLE": "true",
            "ATLASSIAN_OAUTH_CLIENT_ID": "full-client-id",
            "ATLASSIAN_OAUTH_CLIENT_SECRET": "full-client-secret",
            "ATLASSIAN_OAUTH_REDIRECT_URI": "https://example.com/callback",
            "ATLASSIAN_OAUTH_SCOPE": "read:jira-work",
            "ATLASSIAN_OAUTH_CLOUD_ID": "full-cloud-id",
        }.get(key, default)

        # Mock token loading
        with patch.object(OAuthConfig, "load_tokens", return_value={}):
            config = OAuthConfig.from_env()

            # Should return full config, not minimal
            assert config is not None
            assert config.client_id == "full-client-id"
            assert config.client_secret == "full-client-secret"
            assert config.redirect_uri == "https://example.com/callback"
            assert config.scope == "read:jira-work"
            assert config.cloud_id == "full-cloud-id"


class TestBYOAccessTokenOAuthConfig:
    """Tests for the BYOAccessTokenOAuthConfig class."""

    def test_init_with_required_params(self):
        """Test initialization with required parameters."""
        config = BYOAccessTokenOAuthConfig(
            cloud_id="byo-cloud-id", access_token="byo-access-token"
        )
        assert config.cloud_id == "byo-cloud-id"
        assert config.access_token == "byo-access-token"
        assert config.refresh_token is None
        assert config.expires_at is None

    @patch("os.getenv")
    def test_from_env_success(self, mock_getenv):
        """Test from_env success for BYOAccessTokenOAuthConfig."""
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_CLOUD_ID": "env-byo-cloud-id",
            "ATLASSIAN_OAUTH_ACCESS_TOKEN": "env-byo-access-token",
        }.get(key, default)

        config = BYOAccessTokenOAuthConfig.from_env()

        assert config is not None
        assert config.cloud_id == "env-byo-cloud-id"
        assert config.access_token == "env-byo-access-token"
        mock_getenv.assert_any_call("ATLASSIAN_OAUTH_CLOUD_ID")
        mock_getenv.assert_any_call("ATLASSIAN_OAUTH_ACCESS_TOKEN")

    @patch("os.getenv")
    def test_from_env_missing_cloud_id(self, mock_getenv):
        """Test from_env with missing cloud_id for BYOAccessTokenOAuthConfig."""
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_ACCESS_TOKEN": "env-byo-access-token",
        }.get(key, default)

        config = BYOAccessTokenOAuthConfig.from_env()
        assert config is None

    @patch("os.getenv")
    def test_from_env_missing_access_token(self, mock_getenv):
        """Test from_env with missing access_token for BYOAccessTokenOAuthConfig."""
        mock_getenv.side_effect = lambda key, default=None: {
            "ATLASSIAN_OAUTH_CLOUD_ID": "env-byo-cloud-id",
        }.get(key, default)

        config = BYOAccessTokenOAuthConfig.from_env()
        assert config is None

    @patch("os.getenv")
    def test_from_env_missing_both(self, mock_getenv):
        """Test from_env with both missing for BYOAccessTokenOAuthConfig."""
        mock_getenv.return_value = None  # Covers all calls returning None
        config = BYOAccessTokenOAuthConfig.from_env()
        assert config is None


@patch("mcp_atlassian.utils.oauth.BYOAccessTokenOAuthConfig.from_env")
@patch("mcp_atlassian.utils.oauth.OAuthConfig.from_env")
def test_get_oauth_config_prefers_byo_when_both_present(
    mock_oauth_from_env, mock_byo_from_env
):
    """Test get_oauth_config_from_env prefers BYOAccessTokenOAuthConfig when both are configured."""
    mock_byo_config = MagicMock(spec=BYOAccessTokenOAuthConfig)
    mock_byo_from_env.return_value = mock_byo_config
    mock_oauth_config = MagicMock(spec=OAuthConfig)
    mock_oauth_from_env.return_value = mock_oauth_config  # This shouldn't be returned

    result = get_oauth_config_from_env()
    assert result == mock_byo_config
    mock_byo_from_env.assert_called_once()
    mock_oauth_from_env.assert_not_called()  # Standard OAuth should not be called if BYO is found


@patch("mcp_atlassian.utils.oauth.BYOAccessTokenOAuthConfig.from_env")
@patch("mcp_atlassian.utils.oauth.OAuthConfig.from_env")
def test_get_oauth_config_falls_back_to_standard_oauth_config(
    mock_oauth_from_env, mock_byo_from_env
):
    """Test get_oauth_config_from_env falls back to OAuthConfig if BYO is not configured."""
    mock_byo_from_env.return_value = None  # BYO not configured
    mock_oauth_config = MagicMock(spec=OAuthConfig)
    mock_oauth_from_env.return_value = mock_oauth_config

    result = get_oauth_config_from_env()
    assert result == mock_oauth_config  # Should be standard OAuth
    mock_byo_from_env.assert_called_once()
    mock_oauth_from_env.assert_called_once()


@patch("mcp_atlassian.utils.oauth.BYOAccessTokenOAuthConfig.from_env")
@patch("mcp_atlassian.utils.oauth.OAuthConfig.from_env")
def test_get_oauth_config_returns_none_if_both_unavailable(
    mock_oauth_from_env, mock_byo_from_env
):
    """Test get_oauth_config_from_env returns None if neither is available."""
    mock_oauth_from_env.return_value = None
    mock_byo_from_env.return_value = None

    result = get_oauth_config_from_env()
    assert result is None
    mock_oauth_from_env.assert_called_once()
    mock_byo_from_env.assert_called_once()


def test_configure_oauth_session_success_with_oauth_config():
    """Test successful configure_oauth_session with OAuthConfig."""
    session = requests.Session()
    # Explicitly use OAuthConfig and mock its specific methods/attributes
    oauth_config = MagicMock(spec=OAuthConfig)
    oauth_config.access_token = "test-access-token"
    oauth_config.refresh_token = "test-refresh-token"  # Crucial for this path
    oauth_config.ensure_valid_token.return_value = True

    result = configure_oauth_session(session, oauth_config)

    assert result is True
    assert session.headers["Authorization"] == "Bearer test-access-token"
    oauth_config.ensure_valid_token.assert_called_once()


def test_configure_oauth_session_failure_with_oauth_config():
    """Test failed configure_oauth_session with OAuthConfig (token refresh fails)."""
    session = requests.Session()
    oauth_config = MagicMock(spec=OAuthConfig)
    oauth_config.access_token = None  # Start with no access token initially
    oauth_config.refresh_token = "test-refresh-token"  # Has a refresh token
    oauth_config.ensure_valid_token.return_value = False  # Refresh fails

    result = configure_oauth_session(session, oauth_config)

    assert result is False
    assert "Authorization" not in session.headers
    oauth_config.ensure_valid_token.assert_called_once()


def test_configure_oauth_session_success_with_byo_config():
    """Test successful configure_oauth_session with BYOAccessTokenOAuthConfig."""
    session = requests.Session()
    byo_config = BYOAccessTokenOAuthConfig(
        cloud_id="byo-cloud-id", access_token="byo-valid-token"
    )
    # Ensure ensure_valid_token is not called on BYOAccessTokenOAuthConfig if it were a MagicMock
    # by not creating it as a MagicMock or by not setting ensure_valid_token if it were.

    result = configure_oauth_session(session, byo_config)

    assert result is True
    assert session.headers["Authorization"] == "Bearer byo-valid-token"


@patch("mcp_atlassian.utils.oauth.logger")
def test_configure_oauth_session_byo_config_empty_token_logs_error(mock_logger):
    """Test configure_oauth_session with BYO config and empty token logs error."""
    session = requests.Session()
    # BYO config with an effectively invalid (empty) access token
    byo_config = BYOAccessTokenOAuthConfig(cloud_id="byo-cloud-id", access_token="")

    result = configure_oauth_session(session, byo_config)

    assert result is False
    assert "Authorization" not in session.headers
    mock_logger.error.assert_called_once_with(
        "configure_oauth_session: oauth access token configuration provided as empty string."
    )


@patch("mcp_atlassian.utils.oauth.logger")
def test_configure_oauth_session_byo_config_no_refresh_token_direct_use(mock_logger):
    """Test BYO config (with access_token, no refresh_token) uses token directly."""
    session = requests.Session()
    oauth_config = BYOAccessTokenOAuthConfig(
        cloud_id="test_cloud_id", access_token="my_access_token"
    )

    # We don't need to mock ensure_valid_token because it shouldn't be called.
    # The actual BYOAccessTokenOAuthConfig instance does not have this method.

    result = configure_oauth_session(session, oauth_config)

    assert result is True
    assert session.headers["Authorization"] == "Bearer my_access_token"
    # Check that the specific log message for direct use is present
    mock_logger.info.assert_any_call(
        "configure_oauth_session: Using provided OAuth access token directly (no refresh_token)."
    )
