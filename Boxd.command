#!/bin/bash
BOXD_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$BOXD_DIR" || exit 1
while true; do
  echo
  echo '1. Compare Word document with fresh Letterboxd export'
  echo '2. Confirm an older pending import (legacy batches only)'
  echo '3. Show status'
  echo '4. Open exports folder'
  echo '5. Exit'
  echo '6. View decision register'
  echo '7. Edit individual decisions'
  echo '8. Edit general rules'
  read -r -p 'Choose: ' BOXD_CHOICE
  case "$BOXD_CHOICE" in
    1)
      BOXD_DOC=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose your exported Movie Blurbs Word document" of type {"org.openxmlformats.wordprocessingml.document"})') || continue
      BOXD_EXPORT=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose your fresh Letterboxd account export ZIP" of type {"public.zip-archive"})') || continue
      echo "Document: $BOXD_DOC"
      echo "Letterboxd export: $BOXD_EXPORT"
      ./boxd prepare "$BOXD_DOC" "$BOXD_EXPORT"
      ;;
    2)
      read -r -p 'Batch ID: ' BOXD_BATCH
      read -r -p 'Have ALL films in this batch successfully imported? Type IMPORTED to confirm: ' BOXD_CONFIRM
      if [ "$BOXD_CONFIRM" = 'IMPORTED' ]; then
        ./boxd confirm "$BOXD_BATCH" --all --yes
      else
        echo 'Nothing confirmed. Use the README partial-confirmation command if needed.'
      fi
      ;;
    3) ./boxd status ;;
    4) mkdir -p exports; /usr/bin/open exports ;;
    5|'') exit 0 ;;
    6) ./boxd decisions && /usr/bin/open private/decision-register.md ;;
    7) /usr/bin/open -e private/decisions.json ;;
    8) /usr/bin/open -e private/rules.json ;;
    *) echo 'Choose a number from 1 to 8.' ;;
  esac
done
