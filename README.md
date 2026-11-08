Python console app that pulls, parses, and stores 
real-estate deed records from the Jefferson County Clerk's search page: [search.jeffersondeeds.com](https://search.jeffersondeeds.com).
For simplicity, the app currently only works one day at a time.

To use, simply run
```bash
$ python3 collector.py
```
and enter your Jefferson County Clerk's account information, as well as the desired search date, 
as exampled here:
```bash
$ python3 collector.py

Enter username: jdoe123
Enter password: mypass
Enter date to search (MM/DD/YYYY): 09/28/2026
```