#!/usr/bin/env python3
import os

import aws_cdk as cdk
from dotenv import load_dotenv

from nook.nook_stack import NookStack

load_dotenv()

if __name__ == "__main__":
    app = cdk.App()

    NookStack(
        app,
        construct_id="NookStack",
        env_vars={
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
            "REDDIT_CLIENT_ID": os.environ.get("REDDIT_CLIENT_ID"),
            "REDDIT_CLIENT_SECRET": os.environ.get("REDDIT_CLIENT_SECRET"),
            "REDDIT_USER_AGENT": os.environ.get("REDDIT_USER_AGENT"),
        },
        env=cdk.Environment(
            region=os.getenv("CDK_DEFAULT_REGION"),
        ),
    )
    app.synth()
