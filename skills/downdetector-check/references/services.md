# Known Monitored Services

These are the services currently configured in DDBot (`/opt/ddbot/.env`).
Use the slug (URL-safe name) when calling check_status.py or constructing URLs.

| Service     | Slug        | DownDetector URL                                      | isitdownrightnow URL                              |
|-------------|-------------|-------------------------------------------------------|---------------------------------------------------|
| MTN         | mtn         | https://downdetector.co.za/status/mtn/               | https://www.isitdownrightnow.com/mtn.com.html     |
| Vodacom     | vodacom     | https://downdetector.co.za/status/vodacom/           | https://www.isitdownrightnow.com/vodacom.com.html |
| FNB         | fnb         | https://downdetector.co.za/status/fnb/               | https://www.isitdownrightnow.com/fnb.co.za.html   |
| Telkom      | telkom      | https://downdetector.co.za/status/telkom/            | https://www.isitdownrightnow.com/telkom.co.za.html|
| Standard Bank | standard-bank | https://downdetector.co.za/status/standard-bank/ | N/A                                               |
| Netflix     | netflix     | https://downdetector.co.za/status/netflix/           | https://www.isitdownrightnow.com/netflix.com.html |

## Notification Config
- **Threshold:** 10 reports (matches DDBot's DD_THRESHOLD)
- **WhatsApp group:** `120363318957098697@g.us`
- **Personal number:** `+27786385989`
- Send to group always; also send to personal number when triggered manually

## Notes
- DDBot currently only monitors `mtn` by default (DD_SERVICES=mtn in /opt/ddbot/.env)
- downdetector.co.za returns 403 on plain HTTP — use browser tool instead.
- isitdownrightnow.com works without a browser for most services.
- For unlisted services, try the slug as the service name on downdetector.co.za.
