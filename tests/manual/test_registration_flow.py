#!/usr/bin/env python3
"""Test registration flow for learning tools"""

import logging
logging.basicConfig(level=logging.DEBUG)

from core.tools.tool_registry import ToolRegistry, _register_tool_lazy
from core.tools.learning_tools import VisualizeLearningProgressTool
from core.tools.tool_registry import Primitive

print("\n" + "="*80)
print("TESTING REGISTRATION FLOW")
print("="*80)

# Create fresh registry
registry = ToolRegistry()

print("\n1. Before registration:")
print(f"   primitive_index: {registry.primitive_index}")

print("\n2. Registering VisualizeLearningProgressTool...")

# Simulate _register_tool_lazy
metadata_instance = VisualizeLearningProgressTool()
tool_name = metadata_instance.name

print(f"   Tool name: {tool_name}")
print(f"   Has primitive_profile: {bool(getattr(metadata_instance, 'primitive_profile', None))}")

if getattr(metadata_instance, 'primitive_profile', None):
    primitives = list(metadata_instance.primitive_profile.primitive_names())
    print(f"   Declared primitives: {[p.value for p in primitives]}")
else:
    primitives = None
    print(f"   ❌ No primitives declared")

# Register factory
registry.register_factory(
    tool_name,
    VisualizeLearningProgressTool,
    primitives=primitives,
    category=metadata_instance.category,
    safety_level=metadata_instance.safety_level
)

print("\n3. After registration:")
print(f"   tool_factories: {list(registry.tool_factories.keys())}")
print(f"   primitive_index: {registry.primitive_index}")

print("\n4. The index, for one primitive it declares:")
print(f"   Filed under CAUSAL_REASONING: {registry.primitive_index.get(Primitive.CAUSAL_REASONING, [])}")
