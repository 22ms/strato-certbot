"""Certbot-Strato-API Class"""

import os
import re
import urllib

import pyotp
import requests
from bs4 import BeautifulSoup


class CertbotStratoApi:
    """Class to validate domains for Certbot with dns-01 challange"""

    def __init__(self, api_url=None):
        """Initializes the data structure"""
        if api_url is None:
            self.api_url = "https://www.strato.de/apps/CustomerService"
        else:
            self.api_url = api_url

        self.acme_challenge_label = "_acme-challenge"

        # Domain of the requested certificate
        #   root-zone period and acme-challenge lable will be removed
        # _acme-challenge.subdomain.example.com. -> subdomain.example.com
        self.domain_name = re.sub(f"^{self.acme_challenge_label}\\.|\\.$", "", os.environ["CERTBOT_DOMAIN"])
        # Second Level Domain:
        # example.com
        self.second_level_domain_name = re.search(r"([\w-]+\.[\w-]+)$",self.domain_name).group(1)
        # Subdomain: All parts under the second level domain
        # subdomain.example.com -> subdomain
        self.subdomain = self.extract_subdomain()

        # TXT-Record key combination of acme-challenge label and subdomain if exists
        self.txt_key = self.acme_challenge_label + ("" if len(self.subdomain) == 0 else "." + self.subdomain)
        self.txt_value = os.environ["CERTBOT_VALIDATION"]

        print(f"INFO: domain_name: {self.domain_name}")
        print(f"INFO: second_level_domain_name: {self.second_level_domain_name}")
        print(f"INFO: subdomain: {self.subdomain}")

        print(f"INFO: txt_key: {self.txt_key}")
        print(f"INFO: txt_value: {self.txt_value}")

        # setup session for cookie sharing
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0"
        }
        self.http_session = requests.session()
        self.http_session.headers.update(headers)

        # Set later
        self.session_id = ""
        self.package_id = 0
        self.records = []

    def login_2fa(
        self,
        response: requests.Response,
        username: str,
        totp_secret: str,
        totp_devicename: str,
    ) -> requests.Response:
        """Login with Two-factor authentication by TOTP on Strato website.

        :param str totp_secret: 2FA TOTP secret hash
        :param str totp_devicename: 2FA TOTP device name

        :returns: Original response or 2FA response
        :rtype: requests.Response

        """
        # Is 2FA used
        soup = BeautifulSoup(response.text, "html.parser")
        if (
            soup.find("h1", string=re.compile("Zwei\\-Faktor\\-Authentifizierung"))
            is None
        ):
            print("INFO: 2FA is not used.")
            return response
        if (not totp_secret) or (not totp_devicename):
            print("ERROR: 2FA parameter is not completely set.")
            return response

        param = {"identifier": username}

        # Set parameter 'totp_token'
        totp_input = soup.find("input", attrs={"type": "hidden", "name": "totp_token"})
        if totp_input is not None:
            param["totp_token"] = totp_input["value"]
        else:
            print("ERROR: Parsing error on 2FA site by totp_token.")
            return response

        # Set parameter 'action_customer_login.x'
        param["action_customer_login.x"] = 1

        # Set parameter pw_id
        for device in soup.select(f"option[value*='{username}']"):
            if totp_devicename.strip() == device.text.strip():
                param["pw_id"] = device.attrs["value"]
                break

        if param.get("pw_id") is None:
            print("ERROR: Parsing error on 2FA site by device name.")
            return response

        # Set parameter 'totp'
        param["totp"] = pyotp.TOTP(totp_secret).now()
        print(f'DEBUG: totp: {param.get("totp")}')

        request = self.http_session.post(self.api_url, param)
        return request

    def login(
        self,
        username: str,
        password: str,
        totp_secret: str = None,
        totp_devicename: str = None,
    ) -> bool:
        """Login to Strato website. Requests session ID.

        :param str username: Username or customer number of
                'STRATO Customer Login'
        :param str password: Password of 'STRATO Customer Login'
        :param str totp-secret: 2FA TOTP secret hash
        :param str totp-devicename: 2FA TOTP device name

        :returns: Successful login
        :rtype: bool

        """
        # request session id
        request = self.http_session.get("https://config.strato.de/auth/connect")
        if request.history and request.status_code == 200:
            login_url = request.url
        else:
            login_url = "https://config.strato.de/auth/connect"

        parsed_login_url = urllib.parse.urlparse(login_url)
        login_query_params = urllib.parse.parse_qs(parsed_login_url.query)
        data_param = login_query_params.get("data", [None])[0]

        if data_param is None:
            print("ERROR: Could not retrieve login data from Strato.")
            return False

        data = {
            "strato_locale": "de",
            "data": data_param,
            "username": username,
            "password": password,
        }

        request = self.http_session.post("https://login.stratoserver.net/login", data=data)
        if "PHPSESSID" not in self.http_session.cookies:
            print("ERROR: Could not retrieve PHPSESSID cookie from Strato.")
            return False
        
        request = self.http_session.get(
            "https://config.strato.de/domainuebersicht",
        )

        soup = BeautifulSoup(request.text, "html.parser")
        iframe = soup.find("iframe", id="ksbIframe")
        if iframe and iframe.has_attr("src"):
            iframe_src = iframe["src"]
        else:
            print("ERROR: Could not find iframe with id 'ksbIframe' in domain overview.")

        request = self.http_session.get(
            iframe_src,
        )

        parsed_iframe_url = urllib.parse.urlparse(iframe_src)
        iframe_query_params = urllib.parse.parse_qs(parsed_iframe_url.query)
        session_id = iframe_query_params.get("sessionID", [None])[0]
        if session_id is None:
            print("ERROR: Could not retrieve sessionID from iframe src.")
            return False
        self.session_id = session_id

        return True

    def get_package_id(self) -> None:
        """Requests package ID for the selected domain."""
        # request strato packages
        request = self.http_session.get(
            self.api_url,
            params={
                "sessionID": self.session_id,
                "cID": 0,
                "node": "kds_CustomerEntryPage",
            },
        )
        soup = BeautifulSoup(request.text, "html.parser")
        package_anchor = soup.select_one(
            "#package_list > tbody >"
            f' tr:has(.package-information:-soup-contains("{self.second_level_domain_name}"))'
            " .jss_with_own_packagename a"
        )
        if package_anchor:
            if package_anchor.has_attr("href"):
                link_target = urllib.parse.urlparse(package_anchor["href"])
                self.package_id = urllib.parse.parse_qs(link_target.query)["cID"][0]
                print(f"INFO: strato package id (cID): {self.package_id}")
                return

        print(
            f"ERROR: Domain {self.second_level_domain_name} not "
            "found in strato packages. Using fallback cID=1"
        )
        self.package_id = 1

    def extract_subdomain(self) -> str:
        if self.domain_name == self.second_level_domain_name:
            return ""
        if self.domain_name.endswith(self.second_level_domain_name):
            # Compatibility with Python versions before 3.9: using
            # len()-based method instead of removesuffix()
            subdomain = self.domain_name[: -len("." + self.second_level_domain_name)]
            return subdomain
        raise ValueError(
            f"Domain name {self.domain_name} does not end with {self.second_level_domain_name}"
        )

    def get_txt_records(self) -> None:
        """Requests all txt and cname records related to domain."""
        request = self.http_session.get(
            self.api_url,
            params={
                "sessionID": self.session_id,
                "cID": self.package_id,
                "node": "ManageDomains",
                "action_show_txt_records": "",
                "vhost": self.second_level_domain_name,
            },
        )

        soup = BeautifulSoup(request.text, "html.parser")

        for recordElement in soup.select("div.txt-record-tmpl"):
            prefix_element = recordElement.select_one("input[name='prefix']")
            if prefix_element is None:
                raise AttributeError('Element for record attribute "prefix" not found')
            prefix = prefix_element.attrs["value"]

            type_element = recordElement.select_one("select[name='type'] option[selected]")
            if type_element is None:
                raise AttributeError('Element for record attribute "type" not found')
            type = type_element.text
            if not type in ["TXT", "CNAME"]:
                raise TypeError(f'Attribute "type" with value "{type}" must be a value of: TXT, CNAME')

            value_element = recordElement.select_one("textarea[name='value']")
            if value_element is None:
                raise AttributeError('Element for record attribute "value" not found')
            value = value_element.text

            self.add_txt_record(prefix, type, value)

        print("INFO: Current cname/txt records:")
        list(
            print(f'INFO: - {item["prefix"]} {item["type"]}: {item["value"]}')
            for item in self.records
        )

    def add_txt_record(self, prefix: str, record_type: str, value: str) -> None:
        """Add a txt/cname record.

        :param prefix str: Prefix of record
        :param record_type str: Type of record ('TXT' or 'CNAME')
        :param value str: Value of record

        """
        self.records.append(
            {
                "prefix": prefix,
                "type": record_type,
                "value": value,
            }
        )

    def remove_txt_record(self, prefix: str, record_type: str) -> None:
        """Remove a txt/cname record.

        :param prefix str: Prefix of record
        :param record_type str: Type of record ('TXT' or 'CNAME')

        """
        for i in reversed(range(len(self.records))):
            if (
                self.records[i]["prefix"] == prefix
                and self.records[i]["type"] == record_type
            ):
                self.records.pop(i)

    def set_amce_record(self) -> None:
        """Set or replace AMCE txt record on domain."""
        self.add_txt_record(self.txt_key, "TXT", self.txt_value)

    def reset_amce_record(self) -> None:
        """Reset AMCE txt record on domain."""
        self.remove_txt_record(self.txt_key, "TXT")

    def push_txt_records(self) -> None:
        """Push modified txt records to Strato."""
        print("INFO: New cname/txt records:")
        list(
            print(f'INFO: - {item["prefix"]} {item["type"]}: {item["value"]}')
            for item in self.records
        )

        self.http_session.post(
            self.api_url,
            {
                "sessionID": self.session_id,
                "cID": self.package_id,
                "node": "ManageDomains",
                "vhost": self.second_level_domain_name,
                "spf_type": "NONE",
                "prefix": [r["prefix"] for r in self.records],
                "type": [r["type"] for r in self.records],
                "value": [r["value"] for r in self.records],
                "action_change_txt_records": "Einstellung+übernehmen",
            },
        )
