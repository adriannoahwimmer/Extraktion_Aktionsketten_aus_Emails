// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
/**
 * pst_to_jsonl.js
 * --------------------------------------------------
 * Liest eine Outlook-.pst-Datei und schreibt jede E-Mail als JSON-Zeile in eine
 * Ausgabedatei. Wird von backend/parse_mailbox.py aufgerufen, damit .pst-Dateien
 * ohne externe Programme (readpst/libpst) und ohne C-Compiler eingelesen werden
 * koennen - reines JavaScript (Paket "pst-extractor"), laeuft ueberall, wo Node
 * laeuft (das Frontend braucht Node ohnehin).
 *
 * Aufruf:
 *   node pst_to_jsonl.js <eingabe.pst> <ausgabe.jsonl>
 *
 * Pro Mail eine Zeile:
 *   {"from": "...", "to": "...", "date": "<RFC-1123>", "subject": "...",
 *    "body": "<text/plain>", "body_html": "<html, nur wenn kein Plaintext>"}
 *
 * Es werden nur echte Mails (MessageClass IPM.Note*) gelesen - keine Kalender-
 * eintraege, Kontakte oder Aufgaben. Einmalig vorbereiten:
 *   cd backend/tools/pst && npm install
 */

const fs = require("fs");
const path = require("path");
const { PSTFile } = require("pst-extractor");

const [, , pstPfad, ausgabe] = process.argv;
if (!pstPfad || !ausgabe) {
  console.error("Aufruf: node pst_to_jsonl.js <eingabe.pst> <ausgabe.jsonl>");
  process.exit(2);
}

const MAILS_SEITE = 500; // alle N Mails eine Fortschrittszeile
let gelesen = 0;
let fehler = 0;

const out = fs.openSync(ausgabe, "w");

function absender(mail) {
  const name = (mail.senderName || "").trim();
  let adresse = (mail.senderEmailAddress || "").trim();
  // Exchange-interne Adressen (/O=...) sind keine SMTP-Adressen -> nur Name.
  if (adresse.startsWith("/") || !adresse.includes("@")) adresse = "";
  if (name && adresse) return `${name} <${adresse}>`;
  return adresse || name;
}

function empfaenger(mail) {
  // recipientType: 1 = An, 2 = Cc, 3 = Bcc. Fuer die Analyse reicht "An".
  const liste = [];
  try {
    const n = mail.numberOfRecipients;
    for (let i = 0; i < n; i++) {
      const r = mail.getRecipient(i);
      if (!r || r.recipientType !== 1) continue;
      const smtp = (r.smtpAddress || "").trim();
      const em = (r.emailAddress || "").trim();
      const adr = smtp.includes("@") ? smtp : em.includes("@") ? em : "";
      if (adr) liste.push(adr);
    }
  } catch (_) {
    /* ignorieren, displayTo als Rueckfall */
  }
  return liste.length ? liste.join(", ") : (mail.displayTo || "").trim();
}

function verarbeiteMail(mail) {
  const klasse = mail.messageClass || "";
  if (klasse && !klasse.startsWith("IPM.Note")) return; // kein Kalender/Kontakt/...

  const datum = mail.clientSubmitTime || mail.messageDeliveryTime;
  const body = mail.body || "";
  const eintrag = {
    from: absender(mail),
    to: empfaenger(mail),
    date: datum ? datum.toUTCString() : "",
    subject: mail.subject || "",
    body,
  };
  // HTML nur mitschicken, wenn es keinen Plaintext gibt (Outlook speichert
  // manche Mails ausschliesslich als HTML).
  if (!body.trim()) {
    try {
      eintrag.body_html = mail.bodyHTML || "";
    } catch (_) {
      eintrag.body_html = "";
    }
  }
  fs.writeSync(out, JSON.stringify(eintrag) + "\n");
  gelesen++;
  if (gelesen % MAILS_SEITE === 0) console.log(`  PST: ${gelesen} Mails gelesen ...`);
}

function verarbeiteOrdner(ordner) {
  if (ordner.hasSubfolders) {
    for (const kind of ordner.getSubFolders()) verarbeiteOrdner(kind);
  }
  if (ordner.contentCount > 0) {
    let mail = ordner.getNextChild();
    while (mail != null) {
      try {
        verarbeiteMail(mail);
      } catch (e) {
        fehler++;
      }
      try {
        mail = ordner.getNextChild();
      } catch (e) {
        fehler++;
        break;
      }
    }
  }
}

try {
  const pst = new PSTFile(path.resolve(pstPfad));
  verarbeiteOrdner(pst.getRootFolder());
  pst.close();
} catch (e) {
  console.error(`FEHLER beim Lesen der PST-Datei: ${e && e.message ? e.message : e}`);
  fs.closeSync(out);
  process.exit(1);
}

fs.closeSync(out);
console.log(`PST fertig: ${gelesen} Mails gelesen, ${fehler} uebersprungen (defekt).`);
