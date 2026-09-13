#!/bin/bash
BOXD_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$BOXD_DIR" || exit 1
while true; do
  echo
  echo '1. Prepare from Word document'
  echo '2. Confirm a fully successful import'
  echo '3. Show status'
  echo '4. Open exports folder'
  echo '5. Exit'
  read -r -p 'Choose: ' BOXD_CHOICE
  case "$BOXD_CHOICE" in
    1)
      BOXD_DOC=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose your exported Movie Blurbs Word document" of type {"org.openxmlformats.wordprocessingml.document"})') || continue
      ./boxd prepare "$BOXD_DOC"
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
    *) echo 'Choose a number from 1 to 5.' ;;
  esac
done
