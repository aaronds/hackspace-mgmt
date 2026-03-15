import select
import datetime

import psycopg2
import psycopg2.extensions

import os
import json

from sqlalchemy import create_engine, text
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

SQLALCHEMY_DATABASE_URI=os.environ['SQLALCHEMY_DATABASE_URI']
BHS_SYNC_URL=os.environ['BHS_SYNC_URL']
BHS_SYNC_TOKEN=os.environ['BHS_SYNC_TOKEN']


engine = create_engine(SQLALCHEMY_DATABASE_URI, isolation_level="AUTOCOMMIT")

conn = engine.connect()
conn.execute(text("LISTEN member_updated;").execution_options(autocommit=True))
print("Waiting for notifications on channels 'member_updated' with SQL Alchemy")
while 1:
    if select.select([conn.connection],[],[],30) == ([],[],[]):
        print("No Changes");
    else:
        conn.connection.poll()
        while conn.connection.notifies:
            notify = conn.connection.notifies.pop()

            row = json.loads(notify.payload)
            body = {
                "email" : row['email'], 
                "name" : row['preferred_name'] or row['first_name'] + ' ' + row['last_name'],
                "updated" : row['updated']
            }
            body_json = json.dumps(body).encode("utf-8")

            request = Request(
                BHS_SYNC_URL,
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + BHS_SYNC_TOKEN
                },
                data = body_json,
                method = "PUT"
            )

            try:
                urlopen(request, timeout=5)

            except HTTPError as error:
                print(error.status, error.reason)

            except URLError as error:
                print(error.status, error.reason)

            except TimeoutError:
                print("Request timeout")

