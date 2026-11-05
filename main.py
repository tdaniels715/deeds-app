import os, re, sys
import datetime
import time

import requests
from requests.adapters import HTTPAdapter, Retry
from pathlib import Path

import asyncio, aiohttp, aiofiles
from bs4 import BeautifulSoup
from bs4.element import Tag
from urllib.parse import urlparse, parse_qs, urljoin

import logging
import logging.handlers
from queue import SimpleQueue

# =====================================
logger = logging.getLogger("client")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

log_queue = SimpleQueue() # Create a queue and hook it up to a QueueHandler
queue_handler = logging.handlers.QueueHandler(log_queue)
logger.addHandler(queue_handler) # Bind the QueueHandler to your application's root logger

file_handler = logging.FileHandler("client.log", mode="w")
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

# Create a QueueListener to pull messages off the queue in a background thread
log_listener = logging.handlers.QueueListener(log_queue, file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# then main should use this:
# async def main():
#     log_listener.start() # Start the background log listener
#     try: await {my_async_stuff}
#     finally: log_listener.stop() # Ensure all remaining queued logs are flushed before exiting


# =====================================
# ***** NOTE: END URLs WITH `/` *****
# BASE_URL = "http://127.0.0.1:3000/" # localhost
# BASE_URL = "http://172.27.0.127:3000/" # lab-01
BASE_URL = "https://search.jeffersondeeds.com/" # jcc
# ^This makes them compatible with the `href`s from `<a>` tags

semaphore = asyncio.Semaphore(3)  # max code instances running at once (below with `SEM`)
MAX_ROWS=10 # for debugging; sets how many page elements to process

YEAR="2026"
MONTH="09"
DAY="29"
# =====================================

SEARCHES_DIR = Path(f"search_pages/{YEAR}/{MONTH}")
os.makedirs(SEARCHES_DIR, exist_ok=True)

PDFS_DIR = Path(f"deed_pdfs/{YEAR}/{MONTH}/{DAY}")
os.makedirs(PDFS_DIR, exist_ok=True)

RECORDS_DIR = Path(f"records/{YEAR}/{MONTH}")
os.makedirs(RECORDS_DIR, exist_ok=True)

DETAILS_DIR = Path(f"details_pages/{YEAR}/{MONTH}/{DAY}")
os.makedirs(DETAILS_DIR, exist_ok=True)

def log_wait(logger, t: int|float):
    logger.debug(f"Waiting {t}s");
    time.sleep(t)


async def main(logger, log_listener, q_params):
    log_listener.start()
    logger.debug(f"Starting work for {YEAR}/{MONTH}/{DAY}")

    # toy search data
    q_params = {
        "cnum": "CNUM",
        "itype1": "DED",
        "itype2": "",
        "itype3": "",
        "bDate": f"{MONTH}/{DAY}/{YEAR}",  # site seems to use M/D/YYYY, but for now I will use this for my files
        "eDate": f"{MONTH}/{DAY}/{YEAR}",
        "searchtype": "ITYPE",
        "search": "Execute Search"
    }

    session = requests.Session()
    retries = Retry(total=2, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        logger.debug("Getting login page")
        response = session.get(url_join(BASE_URL,"login.php"))
        response.raise_for_status()
        login_html = response.content.decode()
        login_soup = BeautifulSoup(login_html, "html5lib")

        csrf = login_soup.select("input[name~='csrf_token']")[0].get("value")
        login_params = {
            "username": "tdaniels715",
            "password": "r\"Z7sg5}9Kfq>;s",
            "csrf_token": csrf
        }

        log_wait(logger, 2)

        logger.info("Trying login")
        login_resp = session.post(url_join(BASE_URL,"/login.php"), data=login_params)
        login_resp.raise_for_status()
        logger.info("Login successful")

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

def logout(session, logger):
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

async def record_processor(session, logger, trow: Tag, row_id: int) -> dict|None:
    async with semaphore:  # limits concurrent codes running (vs TCPConnector limiting http connections)
        try:
            details_url = trow.select("FORM[id~=submitDetails0]")[0].a.get("href")
            instnum = parse_qs(urlparse(details_url).query).get("instnum")[0] # ensure we get the unique instrument num
        except Exception as e:
            logger.error(f"(row {row_id}) Could not get instnum: {e}")
            raise e

        try:
            logger.info(f"Working on instnum {instnum}")
            record = await details_processor(session, logger, details_url, instnum)
        except Exception as e:
            logger.error(f"Could not process details (I#{instnum}): {e}")
            await asyncio.sleep(3)
            raise e

        await asyncio.sleep(3)

        try:
            await download_deed_pdf(session, logger, trow, instnum)
        except Exception as e:
            logger.error(f"Could not download PDF (I#{instnum}): {e}")
            raise e
        finally:
            await asyncio.sleep(3)

        logger.info(f"Finished record (I#{instnum})")
        return record

async def details_processor(session, logger, url: str, instnum: str) -> dict|None:
    try:
        logger.info(f"Fetching details page (I#{instnum})")
        async with session.get(BASE_URL+url) as response:
            response.raise_for_status()
            details_html = await response.text()
    except Exception as e:
        logger.error(f"Could not fetch details page (I#{instnum}): {e}")
        raise e

    try:
        logger.debug(f"Saving details page (I#{instnum})")
        with open(DETAILS_DIR/f"{instnum}.html", "w") as file:
            file.write(details_html)
    except Exception as e:
        logger.error(f"Could not save details page (I#{instnum}): {e}")
        raise e

    try:
        logger.debug(f"Parsing details (I#{instnum})")
        record = parse_details_html(logger, details_html, instnum)
        return record
    except Exception as e:
        logger.error(f"Could not parse details (I#{instnum}): {type(e).__name__}: {e}")
        raise e

def parse_details_html(logger, details_html: str, instnum: str) -> dict|None:
    det_page = re.sub(r"\s{2,}", " ", details_html)
    det_page = re.sub(r"Legal Desc:</span>(<br>)*<span[^>]*>", r"Legal Desc: ", det_page)  # easier to get Legal Desc field
    det_soup = BeautifulSoup(det_page, "html5lib")

    record = {"instnum": instnum}
    span_texts = [span.text.strip() for span in det_soup.select("span")]

    for item in span_texts:
        if (match := re.match(r'File Date: ([\d/]+)$', item)) is not None: record.update(
            {'date': match.group(1)})
        if (match := re.match(r'Tax\$ (\d+)$', item)) is not None: record.update({'tax$': match.group(1)})
        if (match := re.match(r'Trans\$ (\d+)$', item)) is not None: record.update({'trans$': match.group(1)})
        if (match := re.match(r'VERIFIED$', item)) is not None: record.update({'verified': True})
        if (match := re.match(r'Doc Type: (\w+)$', item)) is not None: record.update(
            {'inst_type': match.group(1)})
        if (match := re.match(r'Book # (\d+)$', item)) is not None: record.update({'book_num': match.group(1)})
        if (match := re.match(r'Legal Desc: (.*)$', item)) is not None: record.update(
            {'legal_desc': match.group(1)})
        if (match := re.match(r'Page # (\d+)$', item)) is not None:
            page = match.group(1)
            record.update({'page_num': (3-len(page))*'0'+page})  # add leading zeros if needed, e.g. 80 -> 080

    if (tags := det_soup.select("textarea[name~='GRANTORS']")) != []:
        grantors = tags[0].text.strip()
        grantors = re.sub(r"\n", ";", grantors)
        record.update({'grantors': grantors})
    if (tags := det_soup.select("textarea[name~='GRANTEES']")) != []:
        grantees = tags[0].text.strip()
        grantees = re.sub(r"\n", ";", grantees)
        record.update({'grantees': grantees})

    assert record["grantors"] != "", f"Could not get Grantors (I#{instnum})"
    assert record["grantees"] != "", f"Could not get Grantees (I#{instnum})"

    return record

async def download_deed_pdf(session, logger, trow: Tag, instnum: str) -> None:
    try:
        logger.info(f"Downloading PDF (I#{instnum})")
        deed_url = trow.select("td[id~='selectOption']")[0].a.get("href")
        async with session.get(BASE_URL+deed_url) as response:
            response.raise_for_status()
            data = await response.read()
    except Exception as e:
        logger.error(f"Could not fetch deed PDF (I#{instnum}): {e}")
        raise e

    try:
        logger.info(f"Writing PDF (I#{instnum})")
        async with aiofiles.open(PDFS_DIR/f"{instnum}.pdf", "wb") as file:
            await file.write(data)
    except Exception as e:
        logger.error(f"Could not write PDF ({instnum}): {e}")
        raise e

def records_writer(logger, records: list) -> None:
    RECORDS_FILE = RECORDS_DIR/f"{YEAR}{MONTH}{DAY}.csv"
    try:
        RECORDS_FILE.touch(exist_ok=True)
    except:
        logger.error(f"Could not make file {RECORDS_FILE.absolute()}")
        return None

    headers = [
        'instnum',
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
            rec.get("instnum"),
            date.strftime("%Y%m%d"),
            rec.get("inst_type"),
            rec.get("grantors"),
            rec.get("grantees"),
            rec.get("tax$"),
            rec.get("trans$"),
            rec.get("legal_desc"),
            rec.get("book_num"),
            rec.get("page_num"),
            "Verified" if rec.get("verified", False) else "Unverified"
        ])

    with RECORDS_FILE.open('w') as file:
        file.write(",".join(headers)+"\n")
        for record in records:
            if record is None : continue
            try:
                file.write(record_str(record)+"\n")
            except Exception as e:
                logger.error(f"Could not write record (I#{record.get("instnum")}): {e}")

if __name__ == "__main__" :
    asyncio.run(main())