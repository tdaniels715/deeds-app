Python console app that pulls, parses, and stores 
real-estate deed records from the Jefferson County Clerk's search page: [search.jeffersondeeds.com](https://search.jeffersondeeds.com).
For simplicity, the app currently only works one day at a time.

Assuming `uv` is installed, set up via
```bash
git clone https://github.com/tdaniels715/deeds-app.git
cd deeds-app
uv sync
```
and run via
```bash
$ python3 collector.py
```
You will be prompted to enter your Jefferson County Clerk's account information, as well as the 
desired search date, 
as exampled here:
```bash
$ python3 collector.py

Enter username: jdoe123
Enter password: mypass
Enter date to search (MM/DD/YYYY): 09/28/2026
```

After running, say with date `09/28/2026`, the program's root directory is organized as in the 
following example:
```
deeds-app/
├─ deeds_pdfs/
│   └─ 2026/
│       └─ 09/
│           └─ 28/
│               ├─ 2026######.pdf
│               ├─ 2026######.pdf
│               └─ ...
├─ details_pages/
│   └─ 2026/
│       └─ 09/
│           └─ 28/
│               ├─ 2026######.html
│               ├─ 2026######.html
│               └─ ...
├─ records/
│   └─ 2026/
│       └─ 09/
│           ├─ 20260928.csv
│           └─ ...   
└─ search_pages/
    └─ 2026/
        └─ 09/
            ├─ 20260928.html
            └─ ...   
```