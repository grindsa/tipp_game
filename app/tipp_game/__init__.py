"""Project package initialization and runtime compatibility patches."""

import sys


def _patch_django_template_context_copy_for_py314():
	"""Patch Django 4.2 template context copy behavior on Python 3.14."""
	if sys.version_info < (3, 14):
		return

	try:
		from django.template.context import BaseContext
	except Exception:
		return

	if getattr(BaseContext, "_tipp_game_py314_copy_patch", False):
		return

	def _base_context_copy(self):
		# Python 3.14 changed copy() handling for super() objects; create an
		# instance copy directly and keep the context stack shallow-copied.
		duplicate = self.__class__.__new__(self.__class__)
		if hasattr(self, "__dict__"):
			duplicate.__dict__ = self.__dict__.copy()
		duplicate.dicts = self.dicts[:]
		return duplicate

	BaseContext.__copy__ = _base_context_copy
	BaseContext._tipp_game_py314_copy_patch = True


_patch_django_template_context_copy_for_py314()
