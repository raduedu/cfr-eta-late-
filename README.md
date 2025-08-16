# cfr-eta-late-
This is a python script specifically made to track how late CFR (Caile Ferate Romane/Romanian Railway) trains are for time of departure. They are notorious for being late, so this helps me stay on top of their departure times without having to constantly check their site.

this is an example of how to run the script:
py -3 "C:\Users\eradu\Downloads\cfr_alert.py" --url "https://mersultrenurilor.infofer.ro/ro-RO/Rute-trenuri/Videle/Bucuresti-(toate-statiile)" --itinerary 13 --interval 60 --notify-at 30 --alarm-gap 1
py -3 "(python script location)" --url "(url of the specific site you want to check)" --itinerary (nr) --interval (in seconds) --notify-at (mins) --alarm-gap (nr)

legend:
--itinerary - you must count from the top down to whichever train is yours, starting from 0, in the example above, the train 9902 is the 14th train displayed, if we start counting from 0 that means you should write 13
--interval - how often you want the script to run, every 60 seconds in the example above
--notify-at - when you want to get notified, the script will create a beeping sound every time the script runs and the time is below the threshold, in the example once it hits below 30 minutes it will start beeping every 1 minute (bcs of the --interval 60)
--alarm-gap - how often the beep should repeat, in this case it will beep every one second for three consecutive times.

REQUIREMENTS
you will also need to install this via powershell (only the first time you run the script):
py -3 -m pip install beautifulsoup4 python-dateutil plyer playwright
py -3 -m playwright install chromium
