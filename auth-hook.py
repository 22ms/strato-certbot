#!/usr/bin/env python3
import json
import os
import re

import requests


def main():
    # get authentication
    with open("strato-auth.json") as file:
        auth = json.load(file)
        username = auth['username']
        password = auth['password']

    api_url = "https://www.strato.de/apps/CustomerService"
    txt_key = "_acme-challenge"
    txt_value = os.environ['CERTBOT_VALIDATION']
    second_level_domain_name = re.search(r'([^.]+\.\w+)$', os.environ['CERTBOT_DOMAIN']).group(1)
    domain_name = re.search(r'^(\*\.)?([\w\.]+)$', os.environ['CERTBOT_DOMAIN']).group(2)

    # setup session for cookie sharing
    http_session = requests.session()

    # request session id
    request = http_session.get(api_url)
    request = http_session.post(api_url, {
        'identifier': username,
        'passwd': password,
        'action_customer_login.x': "Login"
    })
    session_id = re.search(r'sessionID=(.*?)"', request.text).group(1)

    # request strato packages
    request = http_session.get(api_url, params={
        'sessionID': session_id,
        'node': "kds_CustomerEntryPage"
    })
    m = re.search(r'<div class="cep_product">\s*<a class="customer-link" href="[^"]*cID=(?P<cID>\d+)'
                  r'.*<span [^>]*>[^\/]*' + second_level_domain_name.replace('.', '\.'), request.text)
    cID = m.group("cID")

    # request current cname/txt records
    request = http_session.get(api_url, params={
        'sessionID': session_id,
        'cID': cID,
        'node': "ManageDomains",
        'action_show_txt_records': '',
        'vhost': domain_name
    })
    records = []
    for m in re.finditer(r'<input [^>]*value="(?P<prefix>[^"]*)"[^>]*name="prefix"[^>]*>.*'
                         r'<select [^>]*name="type"[^>]*>.*'
                         r'<option[^>]*value="(?P<type>[^"]*)"[^>]*selected[^>]*>.*'
                         r'</select>.*'
                         r'<textarea [^>]*name="value"[^>]*>(?P<value>.*)</textarea>', request.text):
        records.append({
            'prefix': m.group('prefix'),
            'type': m.group('type'),
            'value': m.group('value')
        })

    # add/replace txt record
    for i in reversed(range(len(records))):
        if records[i]['prefix'] == txt_key and records[i]['type'] == "TXT":
            records.pop(i)

    records.append({
        'prefix': txt_key,
        'type': "TXT",
        'value': txt_value,
    })

    # set records
    http_session.post(api_url, {
        'sessionID': session_id,
        'cID': cID,
        'node': "ManageDomains",
        'vhost': domain_name,
        'spf_type': "NONE",
        'prefix': [r['prefix'] for r in records],
        'type': [r['type'] for r in records],
        'value': [r['value'] for r in records],
        'action_change_txt_records': "Einstellung+übernehmen"
    })


if __name__ == "__main__":
    main()
