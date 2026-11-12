"""Bounded resource limit constants for NetArchitect AI.

These constants cap nodes, links, scenarios, optimization runs, and agent
workflows so the application stays within Streamlit Community Cloud Free
resource limits. This module contains no logic - only constants with
explanatory comments.
"""

# Maximum number of network nodes (devices) modeled in a single topology.
MAX_NODES: int = 500

# Maximum number of links (edges) modeled in a single topology.
MAX_EDGES: int = 2000

# Maximum number of subnets in one addressing plan or VLSM allocation.
MAX_SUBNETS: int = 256

# Maximum number of host addresses requested or assigned for one subnet.
# Address arithmetic never enumerates hosts, so this caps user requests rather
# than loop iterations.
MAX_HOSTS_PER_SUBNET: int = 1_000_000

# Maximum number of alternative simple paths returned for one source/destination
# pair. Keeps k-shortest-path enumeration bounded on the deployment target.
MAX_ALTERNATIVE_PATHS: int = 10

# Maximum number of what-if scenarios retained for comparison.
MAX_SCENARIOS: int = 50

# Maximum iterations for any single optimization run.
MAX_OPTIMIZATION_ITERATIONS: int = 1000

# Maximum population size for population-based optimization algorithms.
MAX_POPULATION: int = 200

# Maximum wall-clock seconds for a single simulation run.
MAX_SIMULATION_RUNTIME_SECONDS: int = 30

# Maximum retries an agent may attempt on a recoverable tool failure.
MAX_AGENT_RETRIES: int = 3

# Maximum number of steps in a single agent workflow before it must stop.
MAX_WORKFLOW_STEPS: int = 50
