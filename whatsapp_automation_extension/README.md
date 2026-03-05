# EasyMentor WhatsApp Auto Sender (Chrome Extension)

## Install
1. Open `chrome://extensions/`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select folder: `whatsapp_automation_extension`

## Use
1. Login to WhatsApp Web once in browser.
2. In EasyMentor mentor page: **Whatsapp Message to Mentees**
3. Enter message and choose target.
4. Click **Start Auto (Extension)**.
5. Keep WhatsApp tab in foreground for best reliability.

## Notes
- This automation runs in WhatsApp Web tab by reading queue from `window.name`.
- If WhatsApp UI changes, selectors may need update in `whatsapp_content.js`.
- Keep popup blocking disabled for your portal domain.
