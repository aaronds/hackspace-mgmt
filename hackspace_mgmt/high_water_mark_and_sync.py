import os
import json

from sqlalchemy import create_engine, text, select, DateTime
from sqlalchemy.orm import Session
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from models import Member
from datetime import date, datetime, timedelta, timezone
from time import sleep

SQLALCHEMY_DATABASE_URI=os.environ['SQLALCHEMY_DATABASE_URI']
BHS_SYNC_URL=os.environ['BHS_SYNC_URL']
BHS_SYNC_TOKEN=os.environ['BHS_SYNC_TOKEN']

engine = create_engine(SQLALCHEMY_DATABASE_URI, isolation_level="AUTOCOMMIT")
conn = engine.connect()

with open("member-hwm.json") as hwm_data:
    hwm = json.loads(hwm_data.read())
    hwm_data.close()

print(hwm)

with Session(engine) as session:
        latest = datetime.fromisoformat(hwm['latest'])
        latest_next = latest;
        stmt = select(Member).where(Member.updated > latest)
        for user in session.scalars(stmt):

            if not hwm.get('initialised') and user.end_date:
                continue

            body = {
                "email" : user.email,
                "display_name" : user.preferred_name or user.first_name + ' ' + user.last_name,
                "updated" : user.updated.isoformat(),
                "end_date" : str(user.end_date)
            }

            body_json = json.dumps(body).encode("utf-8")

            request = Request(
                BHS_SYNC_URL + str(user.id),
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
                break;

            except URLError as error:
                print(error, error.reason)
                break;

            except TimeoutError:
                print("Request timeout")
                break;

            latest_next = user.updated

            sleep(0.1)

        hwm_next = {
            "initialised" : True,
            "now" : datetime.now().isoformat(),
            "latest" : latest_next.isoformat()
        }

if not hwm_next :
    exit(1)

with open("member-hwm.json", "w") as f:
    json.dump(hwm_next, f)

