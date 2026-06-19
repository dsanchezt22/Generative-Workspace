"""Screenshot capture/transform engine.

A staged pipeline that turns a reference screenshot into a faithful Trus
ModuleConfig: CAPTURE the image at full fidelity into an intermediate
representation (IR), then TRANSFORM that IR down onto the trusted component
library without dropping any functional element, score the result, and store it
so it seeds future generation. See `engine.capture_to_layout`.
"""
