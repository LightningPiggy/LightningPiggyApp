# Sound effect credits

All files were converted to 16 kHz mono 16-bit PCM WAV, trimmed, and
conditioned for the device speaker: 45 ms of leading silence so a codec's
start-of-playback transient lands before the sound (the ClipTV convention),
a 10 ms fade-in, a 20 Hz high-pass to remove DC offset, a fade-out, a 20 ms
silent tail, then peak-normalized to -1 dB. Recipe (ffmpeg):

    -af aresample=16000,highpass=f=20:poles=2,afade=t=in:d=0.010,\
        afade=t=out:st=<end-0.15>:d=0.15,alimiter=limit=0.89,adelay=45|45,apad=pad_dur=0.02

The originals are on Wikimedia Commons and Freesound.

## pig_oink.wav
- Source: "Mudchute pig 2.ogg", https://commons.wikimedia.org/wiki/File:Mudchute_pig_2.ogg
- Author: Secretlondon (recorded at Mudchute City Farm, London)
- License: CC BY-SA 3.0, https://creativecommons.org/licenses/by-sa/3.0/
- Changes: conditioned as above

## pig_squeal.wav
- Source: "618483 foleyhaven piglet-squeal-01.flac", https://commons.wikimedia.org/wiki/File:618483_foleyhaven_piglet-squeal-01.flac
- Original: https://freesound.org/people/Foleyhaven/sounds/618483/
- Author: Foleyhaven
- License: CC0 1.0 (public domain dedication), https://creativecommons.org/publicdomain/zero/1.0/
- Changes: trimmed to 1.5 s, conditioned as above

## pig_hungry.wav
- Source: "Angry Pig Oinking", https://freesound.org/people/Jofae/sounds/352698/
- Author: Jofae ("my hungry pig squealing and grunting angrily at me")
- License: CC0 1.0 (public domain dedication), https://creativecommons.org/publicdomain/zero/1.0/
- Changes: 1.3 s excerpt from the start of the recording, conditioned as above
