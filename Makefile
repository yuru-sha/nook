cdk-deploy:
	cp nook/lambda/common/requirements.txt nook/lambda/tech_feed/requirements-common.txt
	cp nook/lambda/common/python/gemini_client.py nook/lambda/tech_feed/gemini_client.py
	cdk deploy
	rm nook/lambda/tech_feed/requirements-common.txt
	rm nook/lambda/tech_feed/gemini_client.py
