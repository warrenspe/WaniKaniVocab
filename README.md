# WaniKaniVocab
Generates apkg files based on your current WaniKani progress for drilling Audio -> Meaning.

Requires python to run.

### Usage:  
Install dependencies (once) using **python -m pip install -r requirements.txt**  
Create an API Token through WaniKani here: https://www.wanikani.com/settings/personal_access_token  
Run the program using **python gen_apkg.py --api-token ...**  
Where the **...** is replaced with the **API token** from above  
Import the resulting **wanikani_vocab.apkg** into Anki  

The script only generates anki cards for levels that you've completed in anki.  As you level up, the program can be re-run to generate new apkg files that can be re-imported into anki to create new study cards.
