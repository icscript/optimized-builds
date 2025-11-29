## pull from our icscript polkadot-optimized main to the local to refresh the local files on the server:
cd ~/polkadot-optimized
git pull origin main

## analyze your results:
echo "showing newest feather file at the top:"
cd ~/polkadot-optimized && ls -t processed/todo/

### Run analysis using simple script we made:
python3 analyze_simple.py processed/todo/stable2509-2_fernando-bue_2025-Nov-28_08h

## Regarding Jupyter on headless server
### If you ever want to use the notebook, you can SSH tunnel:

### From your LOCAL machine:
ssh -L 8888:localhost:8888 ubuntu@your-server-ip

### Then on server:
jupyter notebook

### Then open http://localhost:8888 in your LOCAL browser
