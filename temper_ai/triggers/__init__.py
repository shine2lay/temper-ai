"""Triggers: something outside temper happens, and a workflow starts.

A trigger is a small rule in ``configs/triggers/`` naming the event it
waits for and the workflow it starts, with the event's fields mapped onto
the workflow's inputs. ``rules`` loads and renders them; each source
(``linear``) checks its deliveries are genuine and decides what matches.
"""
