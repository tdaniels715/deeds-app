import os, re, sys
import time
import requests
from requests.adapters import HTTPAdapter, Retry

from deeds_collector.init_tools import *
from deeds_collector.processors import *

import asyncio, aiohttp
from bs4 import BeautifulSoup
from bs4.element import Tag
from urllib.parse import urlparse, parse_qs, urljoin

# =====================================
#   "Constants"
BASE_URL = "https://search.jeffersondeeds.com/" # jcc
semaphore = asyncio.Semaphore(3)  # max code instances running at once (below with `SEM`)
# MAX_ROWS=10 # for debugging; sets how many page elements to process

login_params = {
    "username": "tdaniels715",
    "password": "r\"Z7sg5}9Kfq>;s",
    "csrf_token": csrf
}

# =====================================
# for explicitly slowing the program to avoid rate limiting, etc.
def log_wait(logger, t: int|float) -> None:
    logger.debug(f"Waiting {t}s");
    time.sleep(t)

# =====================================
# =====================================
async def main(logger, log_listener, q_params):
    log_listener.start()
    logger.debug(f"Starting work for {YEAR}/{MONTH}/{DAY}")

    session = requests.Session()
    retries = Retry(total=2, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        session = login(session, logger, USER, PASS)
        log_wait(logger, 2)

        try:
            await main_search(session, logger, q_params)
        except Exception as e:
            logger.error(f"main search had errors: {e}")
        log_wait(logger, 2)

        try:
            logout(session, logger)
        except Exception as e:
            logger.error(f"Error in logging out: {e}")

    except Exception as e:
        logger.error(f"Login unsuccessful: {e}")

    finally:
        logger.debug(f"Stopping work for {YEAR}/{MONTH}/{DAY}")
        log_listener.stop()

def login(session, logger, user: str, password: str) -> requests.Session:
    logger.debug("Getting login page")
    response = session.get(urljoin(BASE_URL, "login.php"))
    response.raise_for_status()
    login_html = response.content.decode()
    login_soup = BeautifulSoup(login_html, "html5lib")

    csrf = login_soup.select("input[name~='csrf_token']")[0].get("value")
    login_params = {
        "username": user,
        "password": password,
        "csrf_token": csrf
    }
    log_wait(logger, 2)  # being slow for safety

    logger.info("Trying login")
    login_resp = session.post(urljoin(BASE_URL, "/login.php"), data=login_params)
    login_resp.raise_for_status()
    logger.info("Login successful")

    return session

def logout(session, logger) -> None:
    logger.info(f"Trying logout")
    resp = session.get(BASE_URL+"logout.php")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content.decode(), "html5lib")
    csrf = soup.select("input[name~='csrf_token']")[0].get("value")

    logout_params = {
        "logout": "1",
        "csrf_token": csrf
    }

    resp_2 = session.post(BASE_URL+"logout.php", data=logout_params)
    resp_2.raise_for_status()
    logger.info(f"Logout successful")

async def main_search(session, logger, q_params: dict):
    logger.info(f"Trying search for {YEAR}/{MONTH}/{DAY}")
    try:
        search_resp = session.post(urljoin(BASE_URL,"/p6.php"), data=q_params)
        search_resp.raise_for_status()
        logger.debug(f"Fetched search page")
    except Exception as e:
        logger.error(f"Could not fetch search page")
        raise e

    try:
        logger.debug(f"Trying to decode search results for {YEAR}/{MONTH}/{DAY}")
        search_html = search_resp.content.decode()
        search_soup = BeautifulSoup(search_html, "html5lib")
    except Exception as e:
        logger.error(f"Could not make Soup with search: {type(e).__name__}")
        raise e

    try:
        logger.debug(f"Writing search page to file for {YEAR}/{MONTH}/{DAY}")
        search_file = SEARCHES_DIR/f"{YEAR}{MONTH}{DAY}.html"
        search_file.touch()
        with search_file.open('w') as file:
            file.write(search_html)
    except Exception as e:
        logger.error(f"Could not write search html for {YEAR}{MONTH}{DAY}: {e}")

    record_table = search_soup.select("table")[1].tbody
    rows = record_table.select("tr")

    connector = aiohttp.TCPConnector(limit=100, limit_per_host=0, keepalive_timeout=15)
    timeout = aiohttp.ClientTimeout(total=300)
    cookies = session.cookies.get_dict()

    try:
        logger.debug(f"Starting `records_processors`")
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            cookies=cookies
        ) as session:
            records_tuple = await asyncio.gather(
                *(record_processor(session, logger, trow, i) for i, trow in enumerate(rows))
            )
    except Exception as e:
        logger.error(f"Could not process all records: {e}")
        raise e

    try:
        logger.debug(f"Starting `records_writer`")
        records_writer(logger, records_tuple)  # no await -- writes entire batch at once, for now
    except Exception as e:
        logger.error(f"Could not write records: {e}")
        raise e

async def record_processor(session, logger, trow: Tag, row_id: int) -> dict|None:
    async with semaphore:  # limits concurrent codes running (vs TCPConnector limiting http connections)
        try:
            details_path = trow.select("FORM[id~=submitDetails0]")[0].a.get("href")
            inst_num = parse_qs(urlparse(details_path).query).get("instnum")[0] # ensure we get the unique instrument num
        except Exception as e:
            logger.error(f"(row {row_id}) Could not get inst_num: {e}")
            raise e

        try:
            logger.info(f"Working on inst_num {inst_num}")
            details_url = urljoin(BASE_URL, details_path)
            record = await details_processor(session, logger, details_url, inst_num)
        except Exception as e:
            logger.error(f"Could not process details (I#{inst_num}): {e}")
            await asyncio.sleep(3)
            raise e

        await asyncio.sleep(3)

        try:
            await download_deed_pdf(session, logger, trow, inst_num)
        except Exception as e:
            logger.error(f"Could not download PDF (I#{inst_num}): {e}")
            raise e
        finally:
            await asyncio.sleep(3)

        logger.info(f"Finished record (I#{inst_num})")
        return record


def records_writer(logger, fpath: Path, records: list) -> None:
    fpath = RECORDS_DIR/f"{YEAR}{MONTH}{DAY}.csv"
    try:
        fpath.touch(exist_ok=True)
    except:
        logger.error(f"Could not make file {fpath.absolute()}")
        return None

    headers = [
        'inst_num',
        'date',
        'inst_type',
        'grantors',
        'grantees',
        'tax_amt',
        'trans_amt',
        'legal_desc',
        'book_num',
        'page_num',
        'verified',
    ]

    def record_str(rec: dict) -> str:
        date = datetime.date.strptime(rec.get("date"), "%m/%d/%Y")
        return ",".join([
            rec.get("inst_num"),
            date.strftime("%Y%m%d"),
            rec.get("inst_type"),
            rec.get("grantors"),
            rec.get("grantees"),
            rec.get("tax_amt"),
            rec.get("trans_amt"),
            rec.get("legal_desc"),
            rec.get("book_num"),
            rec.get("page_num"),
            "Verified" if rec.get("verified", False) else "Unverified"
        ])

    with fpath.open('w') as file:
        file.write(",".join(headers)+"\n")
        for record in records:
            if record is None : continue
            try:
                file.write(record_str(record)+"\n")
            except Exception as e:
                logger.error(f"Could not write record (I#{record.get("inst_num")}): {e}")

if __name__ == "__main__" :
    arg_parser = init_parser()
    args = arg_parser.parse_args()

    logger, log_listener = init_logger(
        log_console_level = args.log_console_level,
        log_file_level = args.log_file_level,
        log_file = args.log_file
    )

    if args.user == "":
        USER = input("Enter username: ")
    else: USER = args.user

    if args.password == "":
        PASS = input("Enter password: ")
    else: PASS = args.password

    YEAR, MONTH, DAY = get_date()
    DIRS = init_dirs(YEAR, MONTH, DAY) # dict[str->Path]

    q_params = {
        "cnum": "CNUM",
        "itype1": "DED",
        "itype2": "",
        "itype3": "",
        "bDate": f"{MONTH}/{DAY}/{YEAR}",
        "eDate": f"{MONTH}/{DAY}/{YEAR}",
        "searchtype": "ITYPE",
        "search": "Execute Search"
    }

    asyncio.run(main(logger, log_listener, q_params))