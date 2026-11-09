import re
import aiofiles

from bs4 import BeautifulSoup
from bs4.element import Tag
from pathlib import Path

from deeds_collector.exceptions import *

from urllib.parse import urljoin

async def details_processor(
    session,
    logger,
    details_dir: Path,
    url: str,
    inst_num: str
) -> dict|None:

    try:
        logger.info(f"Fetching details page (I#{inst_num})")
        async with session.get(url) as response:
            response.raise_for_status()
            details_html = await response.text()
    except Exception as e:
        raise DetailsError(f"Could not fetch details page (I#{inst_num}): {e}", e)

    try:
        logger.debug(f"Saving details page (I#{inst_num})")
        with open(details_dir/f"{inst_num}.html", "w") as file:
            file.write(details_html)
    except Exception as e:
        raise DetailsError(f"Could not save details page (I#{inst_num}): {e}", e)

    try:
        logger.debug(f"Parsing details (I#{inst_num})")
        det_page = re.sub(r"\s{2,}", " ", details_html)
        det_page = re.sub(r"Legal Desc:</span>(<br>)*<span[^>]*>", r"Legal Desc: ", det_page)  # easier to get Legal Desc field
        det_soup = BeautifulSoup(det_page, "html5lib")
        record = parse_details_html(logger, details_html, inst_num)
        return record
    except Exception as e:
        raise DetailsError(f"Could not parse details (I#{inst_num}): {type(e).__name__}: {e}", e)

def parse_details_html(logger, details_soup: BeautifulSoup, inst_num: str) -> dict|None:
    record = {"inst_num": inst_num}
    span_texts = [span.text.strip() for span in details_soup.select("span")]

    for item in span_texts:
        if (match := re.match(r'File Date: ([\d/]+)$', item)) is not None: record.update(
            {'date': match.group(1)})
        if (match := re.match(r'Tax\$ (\d+)$', item)) is not None: record.update({'tax_amt': match.group(1)})
        if (match := re.match(r'Trans\$ (\d+)$', item)) is not None: record.update({'trans_amt': match.group(1)})
        if (match := re.match(r'VERIFIED$', item)) is not None: record.update({'verified': True})
        if (match := re.match(r'Doc Type: (\w+)$', item)) is not None: record.update(
            {'inst_type': match.group(1)})
        if (match := re.match(r'Book # (\d+)$', item)) is not None: record.update({'book_num': match.group(1)})
        if (match := re.match(r'Legal Desc: (.*)$', item)) is not None: record.update(
            {'legal_desc': match.group(1)})
        if (match := re.match(r'Page # (\d+)$', item)) is not None:
            page = match.group(1)
            record.update({'page_num': (3-len(page))*'0'+page})  # add leading zeros if needed, e.g. 80 -> 080

    if (tags := details_soup.select("textarea[name~='GRANTORS']")) != []:
        grantors = tags[0].text.strip()
        grantors = re.sub(r"\n", ";", grantors)
        record.update({'grantors': grantors})
    if (tags := details_soup.select("textarea[name~='GRANTEES']")) != []:
        grantees = tags[0].text.strip()
        grantees = re.sub(r"\n", ";", grantees)
        record.update({'grantees': grantees})

    return record

async def download_deed_pdf(session, logger,
                            base_url: str,
                            pdfs_dir: Path,
                            trow: Tag,
                            inst_num: str
                            ) -> None:
    try:
        logger.info(f"Downloading PDF (I#{inst_num})")
        deed_url = trow.select("td[id~='selectOption']")[0].a.get("href")
        async with session.get(urljoin(base_url,deed_url)) as response:
            response.raise_for_status()
            data = await response.read()
    except Exception as e:
        raise PDFError(f"Could not fetch deed PDF (I#{inst_num}): {e}", e)

    try:
        logger.info(f"Writing PDF (I#{inst_num})")
        async with aiofiles.open(pdfs_dir/f"{inst_num}.pdf", "wb") as file:
            await file.write(data)
    except Exception as e:
        raise PDFError(f"Could not write PDF ({inst_num}): {e}", e)
