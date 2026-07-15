# Para-wise Remarks Register

Client-side tool that converts a GST assessment order PDF into a 3-column
para-wise remarks statement (Defect as per order / Taxpayer Reply / Conclusion),
with case details, demand summary, editable cells, and Print / Word export.

Everything runs in the browser — uploaded PDFs never leave the visitor's computer.
`pdf.min.js` / `pdf.worker.min.js` are bundled so the page also works fully offline
(just open `index.html`).

## Serve

Any static file server works:

```bash
python3 -m http.server 8013
```

## Deploy on remarks.jaypokale.me (cloudflared)

One-time setup on the server, from `<server-path>`:

```bash
# 1. create the tunnel (uses the account cert already in .cloudflared/)
TUNNEL_ORIGIN_CERT=$PWD/.cloudflared/cert.pem ./cloudflared tunnel create remarks
# note the tunnel UUID it prints, and move the generated credentials next to the others:
mv ~/.cloudflared/<TUNNEL_ID>.json .cloudflared/remarks.json

# 2. point the DNS record at the tunnel
TUNNEL_ORIGIN_CERT=$PWD/.cloudflared/cert.pem ./cloudflared tunnel route dns remarks remarks.jaypokale.me

# 3. write the config
cp parawise-remarks/deploy/config-remarks.yml.template .cloudflared/config-remarks.yml
#    then edit it: replace <TUNNEL_ID> with the UUID from step 1
```

Run (inside tmux):

```bash
tmux new -s remarks
cd <server-path>/parawise-remarks && python3 -m http.server 8013
# Ctrl+B C for a second tmux window:
cd <server-path> && ./cloudflared --config .cloudflared/config-remarks.yml tunnel run
```

Then open https://remarks.jaypokale.me
