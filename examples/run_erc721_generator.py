#!/usr/bin/env python3
"""
ERC721 Autonomous Generator - Orchestrator Script

End-to-end workflow that uses the framework to autonomously generate
a minimal ERC721 Hardhat project (scaffold, write code, compile, test,
deploy to local node).

Prerequisites:
    - Node.js and npm installed
    - Ollama running with a model pulled (e.g., ollama pull llama3:8b)

Usage:
    python examples/run_erc721_generator.py --model llama3:8b
    python examples/run_erc721_generator.py --contract-name MyNFT --token-name "My NFT" --token-symbol MNFT
"""
import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import jinja2

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.standard_agent import StandardAgent
from src.storage.schemas.agent_config import AgentConfig as SchemaAgentConfig
from src.self_improvement.metrics.erc721_quality import score_erc721_workflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def check_prerequisites() -> bool:
    """Check that required tools are available.

    Returns:
        True if all prerequisites are met
    """
    ok = True

    # Check node
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"Node.js: {result.stdout.strip()}")
        else:
            logger.error("Node.js not working properly")
            ok = False
    except FileNotFoundError:
        logger.error("Node.js not found. Install from https://nodejs.org/")
        ok = False

    # Check npm
    try:
        result = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"npm: {result.stdout.strip()}")
        else:
            logger.error("npm not working properly")
            ok = False
    except FileNotFoundError:
        logger.error("npm not found. Install Node.js from https://nodejs.org/")
        ok = False

    # Check Ollama
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("Ollama: running")
        else:
            logger.warning("Ollama may not be running. Start with: ollama serve")
    except FileNotFoundError:
        logger.warning("Ollama not found. Install from https://ollama.ai/")

    return ok


def create_workspace(base_dir: Path) -> Path:
    """Create an isolated workspace directory.

    Args:
        base_dir: Base directory for workspaces

    Returns:
        Path to the new workspace
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace = base_dir / f"erc721_{timestamp}"
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created workspace: {workspace}")
    return workspace


def load_agent_config(config_path: str) -> SchemaAgentConfig:
    """Load and parse an agent configuration file.

    Args:
        config_path: Path to the YAML config file

    Returns:
        Parsed AgentConfig
    """
    import yaml

    config_file = PROJECT_ROOT / config_path
    with open(config_file) as f:
        raw = yaml.safe_load(f)

    return SchemaAgentConfig(**raw)


class _SafeDict(dict):
    """Dict subclass that returns YAML-safe placeholders for missing keys.

    When Jinja2 renders ``{{ stage_outputs.test }}`` inside a YAML config,
    the value can contain arbitrary LLM text that breaks YAML parsing.
    This wrapper converts dict values to single-line escaped strings so
    they survive YAML round-tripping. The real unescaped values are passed
    to the agent's PromptEngine separately via input_data.
    """

    def __getattr__(self, name: str) -> str:
        val = self.get(name, "")
        # Collapse to single line and escape quotes for YAML safety
        if isinstance(val, str):
            safe = val.replace("\n", " ").replace('"', '\\"')[:200]
        else:
            safe = str(val).replace("\n", " ")[:200]
        return safe


def run_agent_with_input(
    config_path: str,
    input_data: dict,
    llm_model: str,
) -> dict:
    """Run a single agent with the given input data.

    This manually instantiates and runs an agent from a config file,
    handling Jinja2 template variables.

    Args:
        config_path: Path to the agent config YAML
        input_data: Input data dict for the agent
        llm_model: Ollama model name

    Returns:
        Agent response as dict
    """
    import yaml

    config_file = PROJECT_ROOT / config_path
    with open(config_file) as f:
        raw_yaml = f.read()

    # Only render YAML-level config variables (model name, workspace path).
    # The prompt inline template is rendered later by the agent's PromptEngine
    # with full input_data, so we must NOT render prompt variables here —
    # otherwise LLM output embedded in stage_outputs can break YAML syntax.
    #
    # Strategy: replace ONLY the inference.model Jinja2 expression in the raw
    # YAML, then let the agent's PromptEngine handle prompt-level variables.
    from jinja2 import BaseLoader, Environment

    env = Environment(loader=BaseLoader(), undefined=jinja2.Undefined)
    template = env.from_string(raw_yaml)

    # Build a minimal set of variables for YAML-level rendering.
    # We render everything EXCEPT stage_outputs (which can contain
    # arbitrary LLM text that breaks YAML). Stage outputs are only
    # needed inside the prompt, which the agent renders separately.
    yaml_vars = {
        "llm_model": llm_model,
        "workspace_path": input_data.get("workspace_path", ""),
        "contract_name": input_data.get("contract_name", "SimpleNFT"),
        "token_name": input_data.get("token_name", "SimpleNFT"),
        "token_symbol": input_data.get("token_symbol", "SNFT"),
        # Provide stage_outputs as a safe placeholder for YAML rendering.
        # The real value is passed through input_data to the prompt engine.
        "stage_outputs": _SafeDict(input_data.get("stage_outputs", {})),
    }
    rendered_yaml = template.render(**yaml_vars)

    config_dict = yaml.safe_load(rendered_yaml)
    config = SchemaAgentConfig(**config_dict)

    # Log the prompt being sent to the LLM
    agent_inner = config.agent
    prompt_text = agent_inner.prompt.inline if hasattr(agent_inner.prompt, "inline") and agent_inner.prompt.inline else str(agent_inner.prompt)
    logger.info(f"--- LLM PROMPT ({config_path}) ---")
    logger.info(f"Model: {agent_inner.inference.provider}:{agent_inner.inference.model}")
    logger.info(f"Temperature: {agent_inner.inference.temperature}")
    logger.info(f"{prompt_text[:3000]}")
    logger.info("--- END PROMPT ---")

    agent = StandardAgent(config)
    response = agent.execute(input_data)

    # Log the LLM response
    logger.info(f"--- LLM RESPONSE ({config_path}) ---")
    logger.info(f"Output:\n{(response.output or '')[:3000]}")
    if response.reasoning:
        logger.info(f"Reasoning: {response.reasoning[:1000]}")
    if response.tool_calls:
        logger.info(f"Tool calls ({len(response.tool_calls)}):")
        for tc in response.tool_calls:
            logger.info(f"  {tc}")
    if response.error:
        logger.info(f"Error: {response.error}")
    logger.info(f"Tokens: {response.tokens}, Latency: {response.latency_seconds:.1f}s")
    logger.info("--- END RESPONSE ---")

    return {
        "output": response.output,
        "reasoning": response.reasoning,
        "tool_calls": response.tool_calls,
        "tokens": response.tokens,
        "cost": response.estimated_cost_usd,
        "latency": response.latency_seconds,
        "error": response.error,
    }


def run_direct_setup(workspace: Path, contract_name: str, token_name: str, token_symbol: str) -> bool:
    """Directly write project files without LLM (deterministic fallback).

    This ensures the project structure is correct regardless of LLM quality.
    The LLM-driven agents are used when available, but this provides a
    guaranteed baseline.

    Args:
        workspace: Workspace directory path
        contract_name: Solidity contract name
        token_name: ERC721 token name
        token_symbol: ERC721 token symbol

    Returns:
        True if setup succeeded
    """
    logger.info("Writing project files directly (deterministic mode)...")

    # package.json
    package_json = {
        "name": "erc721-project",
        "version": "1.0.0",
        "description": "Minimal ERC721 NFT project",
        "scripts": {
            "compile": "npx hardhat compile",
            "test": "npx hardhat test",
            "deploy": "npx hardhat run scripts/deploy.js",
        },
        "devDependencies": {
            "hardhat": "^2.19.0",
            "@nomicfoundation/hardhat-toolbox": "^4.0.0",
        },
        "dependencies": {
            "@openzeppelin/contracts": "^5.0.0",
        },
    }
    (workspace / "package.json").write_text(json.dumps(package_json, indent=2))

    # hardhat.config.js
    hardhat_config = 'require("@nomicfoundation/hardhat-toolbox");\n\nmodule.exports = {\n  solidity: "0.8.20",\n};\n'
    (workspace / "hardhat.config.js").write_text(hardhat_config)

    # contracts/
    (workspace / "contracts").mkdir(exist_ok=True)
    contract_sol = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {contract_name} is ERC721, Ownable {{
    uint256 private _nextTokenId;

    constructor() ERC721("{token_name}", "{token_symbol}") Ownable(msg.sender) {{
        _nextTokenId = 1;
    }}

    function mint(address to) public onlyOwner returns (uint256) {{
        uint256 tokenId = _nextTokenId;
        _nextTokenId++;
        _mint(to, tokenId);
        return tokenId;
    }}
}}
"""
    (workspace / "contracts" / f"{contract_name}.sol").write_text(contract_sol)

    # test/
    (workspace / "test").mkdir(exist_ok=True)
    test_js = f"""const {{ expect }} = require("chai");
const {{ ethers }} = require("hardhat");

describe("{contract_name}", function () {{
  let contract;
  let owner;
  let addr1;
  let addr2;

  beforeEach(async function () {{
    [owner, addr1, addr2] = await ethers.getSigners();
    const Factory = await ethers.getContractFactory("{contract_name}");
    contract = await Factory.deploy();
    await contract.waitForDeployment();
  }});

  describe("Deployment", function () {{
    it("Should set the correct name and symbol", async function () {{
      expect(await contract.name()).to.equal("{token_name}");
      expect(await contract.symbol()).to.equal("{token_symbol}");
    }});

    it("Should set the deployer as owner", async function () {{
      expect(await contract.owner()).to.equal(owner.address);
    }});
  }});

  describe("Minting", function () {{
    it("Should mint a token to an address", async function () {{
      await contract.mint(addr1.address);
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
      expect(await contract.balanceOf(addr1.address)).to.equal(1);
    }});

    it("Should increment token IDs", async function () {{
      await contract.mint(addr1.address);
      await contract.mint(addr2.address);
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
      expect(await contract.ownerOf(2)).to.equal(addr2.address);
    }});

    it("Should only allow owner to mint", async function () {{
      await expect(
        contract.connect(addr1).mint(addr1.address)
      ).to.be.revertedWithCustomError(contract, "OwnableUnauthorizedAccount");
    }});
  }});

  describe("Transfer", function () {{
    it("Should transfer tokens between accounts", async function () {{
      await contract.mint(addr1.address);
      await contract.connect(addr1).transferFrom(addr1.address, addr2.address, 1);
      expect(await contract.ownerOf(1)).to.equal(addr2.address);
    }});
  }});
}});
"""
    (workspace / "test" / f"{contract_name}.test.js").write_text(test_js)

    # scripts/
    (workspace / "scripts").mkdir(exist_ok=True)
    deploy_js = f"""const {{ ethers }} = require("hardhat");

async function main() {{
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with account:", deployer.address);

  const Factory = await ethers.getContractFactory("{contract_name}");
  const contract = await Factory.deploy();
  await contract.waitForDeployment();

  const address = await contract.getAddress();
  console.log("{contract_name} deployed to:", address);

  // Mint a test token
  const tx = await contract.mint(deployer.address);
  await tx.wait();
  console.log("Minted token #1 to:", deployer.address);
  console.log("Owner of token #1:", await contract.ownerOf(1));
}}

main()
  .then(() => process.exit(0))
  .catch((error) => {{
    console.error(error);
    process.exit(1);
  }});
"""
    (workspace / "scripts" / "deploy.js").write_text(deploy_js)

    logger.info("All project files written successfully")

    # npm install
    logger.info("Running npm install (this may take a minute)...")
    try:
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            logger.info("npm install completed successfully")
            return True
        else:
            logger.error(f"npm install failed: {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("npm install timed out")
        return False
    except Exception as e:
        logger.error(f"npm install error: {e}")
        return False


def run_workflow(
    workspace: Path,
    contract_name: str = "SimpleNFT",
    token_name: str = "SimpleNFT",
    token_symbol: str = "SNFT",
    llm_model: str = "llama3:8b",
    use_llm: bool = True,
    max_fix_loops: int = 3,
) -> dict:
    """Run the complete ERC721 generation workflow.

    Stages:
    1. Scaffold (architect plans structure) - optional with LLM
    2. Code (write files + npm install)
    3. Test (compile + run tests)
    4. Fix (if tests fail, fix and re-test, up to max_fix_loops)

    Args:
        workspace: Workspace directory path
        contract_name: Solidity contract name
        token_name: ERC721 token name
        token_symbol: ERC721 token symbol
        llm_model: Ollama model to use
        use_llm: Whether to use LLM agents (False = deterministic mode)
        max_fix_loops: Maximum fix-test iterations

    Returns:
        Results dict with stage outputs and quality score
    """
    start_time = time.time()
    results = {
        "workspace": str(workspace),
        "contract_name": contract_name,
        "stages": {},
        "quality_score": None,
        "duration_seconds": 0,
    }

    input_data = {
        "contract_name": contract_name,
        "token_name": token_name,
        "token_symbol": token_symbol,
        "workspace_path": str(workspace),
        "llm_model": llm_model,
        "stage_outputs": {},
    }

    if use_llm:
        # Stage 1: Scaffold (architect)
        logger.info("=" * 60)
        logger.info("STAGE 1: Scaffold (Architect)")
        logger.info("=" * 60)
        try:
            scaffold_result = run_agent_with_input(
                "configs/agents/erc721_architect.yaml",
                input_data,
                llm_model,
            )
            results["stages"]["scaffold"] = scaffold_result
            input_data["stage_outputs"]["scaffold"] = scaffold_result.get("output", "")
            logger.info(f"Scaffold complete (tokens: {scaffold_result.get('tokens', 0)})")
        except Exception as e:
            logger.warning(f"Scaffold agent failed: {e}. Continuing with defaults.")
            results["stages"]["scaffold"] = {"error": str(e)}

        # Stage 2: Code (write files)
        logger.info("=" * 60)
        logger.info("STAGE 2: Code (Coder)")
        logger.info("=" * 60)
        try:
            code_result = run_agent_with_input(
                "configs/agents/erc721_coder.yaml",
                input_data,
                llm_model,
            )
            results["stages"]["code"] = code_result
            input_data["stage_outputs"]["code"] = code_result.get("output", "")
            logger.info(f"Code complete (tokens: {code_result.get('tokens', 0)})")
        except Exception as e:
            logger.warning(f"Coder agent failed: {e}. Falling back to direct setup.")
            results["stages"]["code"] = {"error": str(e)}
            # Fallback to direct file writing
            run_direct_setup(workspace, contract_name, token_name, token_symbol)
    else:
        # Direct (deterministic) mode
        logger.info("=" * 60)
        logger.info("Running in deterministic mode (no LLM)")
        logger.info("=" * 60)
        success = run_direct_setup(workspace, contract_name, token_name, token_symbol)
        results["stages"]["direct_setup"] = {"success": success}

    # Ensure files exist (fallback if LLM didn't produce valid tool calls)
    if not (workspace / "package.json").exists():
        logger.warning("LLM output missing files. Running direct setup as fallback.")
        run_direct_setup(workspace, contract_name, token_name, token_symbol)

    # Stage 3: Test
    logger.info("=" * 60)
    logger.info("STAGE 3: Test (Compile + Test)")
    logger.info("=" * 60)

    if use_llm:
        try:
            test_result = run_agent_with_input(
                "configs/agents/erc721_tester.yaml",
                input_data,
                llm_model,
            )
            results["stages"]["test"] = test_result
            input_data["stage_outputs"]["test"] = test_result.get("output", "")
        except Exception as e:
            logger.warning(f"Tester agent failed: {e}. Running compile/test directly.")
            results["stages"]["test"] = {"error": str(e)}
    else:
        # Direct compile and test
        try:
            compile_result = subprocess.run(
                ["npx", "hardhat", "compile"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=120,
            )
            test_result_proc = subprocess.run(
                ["npx", "hardhat", "test"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=120,
            )
            results["stages"]["test"] = {
                "compile_exit": compile_result.returncode,
                "test_exit": test_result_proc.returncode,
                "test_stdout": test_result_proc.stdout[:1000],
            }
        except FileNotFoundError:
            logger.error("npx not found. Install Node.js.")
            results["stages"]["test"] = {"error": "npx not found"}
        except subprocess.TimeoutExpired:
            logger.error("Compile/test timed out")
            results["stages"]["test"] = {"error": "Timed out"}

    # Stage 4: Fix (conditional, up to max_fix_loops)
    fix_iterations = 0
    if use_llm:
        for i in range(max_fix_loops):
            # Check if tests passed (simple heuristic)
            test_output = input_data.get("stage_outputs", {}).get("test", "")
            if '"success": true' in str(test_output).lower() or "passing" in str(test_output).lower():
                # Check if there are failures
                if '"failing": 0' in str(test_output) or "failing" not in str(test_output).lower():
                    logger.info("Tests appear to pass. Skipping fix stage.")
                    break

            logger.info("=" * 60)
            logger.info(f"STAGE 4: Fix (iteration {i + 1}/{max_fix_loops})")
            logger.info("=" * 60)

            try:
                fix_result = run_agent_with_input(
                    "configs/agents/erc721_fixer.yaml",
                    input_data,
                    llm_model,
                )
                results["stages"][f"fix_{i + 1}"] = fix_result
                input_data["stage_outputs"]["fix"] = fix_result.get("output", "")
                fix_iterations += 1

                # Re-test after fix
                test_result = run_agent_with_input(
                    "configs/agents/erc721_tester.yaml",
                    input_data,
                    llm_model,
                )
                results["stages"][f"test_after_fix_{i + 1}"] = test_result
                input_data["stage_outputs"]["test"] = test_result.get("output", "")
            except Exception as e:
                logger.warning(f"Fix iteration {i + 1} failed: {e}")
                results["stages"][f"fix_{i + 1}"] = {"error": str(e)}
                break

    results["fix_iterations"] = fix_iterations

    # Score the output
    logger.info("=" * 60)
    logger.info("SCORING: Quality Assessment")
    logger.info("=" * 60)

    try:
        quality = score_erc721_workflow(
            workspace_path=str(workspace),
            contract_name=contract_name,
            run_commands=True,
        )
        results["quality_score"] = quality.total_score
        results["quality_breakdown"] = quality.breakdown
        logger.info(f"Quality Score: {quality.total_score:.2f}")
        for metric, data in quality.breakdown.items():
            logger.info(f"  {metric}: {data['score']:.2f}")
            details = data.get("details", {})
            if isinstance(details, dict):
                # Show stdout/stderr for command-based metrics
                if "stdout" in details and details["stdout"]:
                    logger.info(f"    stdout: {details['stdout']}")
                if "stderr" in details and details["stderr"]:
                    logger.info(f"    stderr: {details['stderr']}")
                # Show found/missing for structure check
                if "found" in details:
                    logger.info(f"    found: {details['found']}")
                if "missing" in details:
                    logger.info(f"    missing: {details['missing']}")
                # Show code quality checks
                for key, val in details.items():
                    if key not in ("stdout", "stderr", "exit_code", "found", "missing", "passing", "failing"):
                        logger.info(f"    {key}: {val}")
                # Show test counts
                if "passing" in details:
                    logger.info(f"    passing: {details['passing']}, failing: {details['failing']}")
            elif isinstance(details, str):
                logger.info(f"    {details}")
    except Exception as e:
        logger.error(f"Quality scoring failed: {e}")
        results["quality_score"] = 0.0

    results["duration_seconds"] = time.time() - start_time
    return results


def main():
    parser = argparse.ArgumentParser(
        description="ERC721 Autonomous Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default="llama3:8b", help="Ollama model name")
    parser.add_argument("--contract-name", default="SimpleNFT", help="Contract name")
    parser.add_argument("--token-name", default="SimpleNFT", help="Token name")
    parser.add_argument("--token-symbol", default="SNFT", help="Token symbol")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run in deterministic mode without LLM",
    )
    parser.add_argument(
        "--max-fix-loops",
        type=int,
        default=3,
        help="Maximum fix-test iterations",
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(PROJECT_ROOT / "workspace"),
        help="Base directory for workspaces",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ERC721 Autonomous Generator")
    print("=" * 60)
    print(f"  Model: {args.model}")
    print(f"  Contract: {args.contract_name}")
    print(f"  Token: {args.token_name} ({args.token_symbol})")
    print(f"  LLM: {'Disabled' if args.no_llm else 'Enabled'}")
    print("=" * 60)

    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites not met. Please install missing tools.")
        sys.exit(1)

    # Create workspace
    workspace = create_workspace(Path(args.workspace_dir))

    # Run workflow
    results = run_workflow(
        workspace=workspace,
        contract_name=args.contract_name,
        token_name=args.token_name,
        token_symbol=args.token_symbol,
        llm_model=args.model,
        use_llm=not args.no_llm,
        max_fix_loops=args.max_fix_loops,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Workspace: {results['workspace']}")
    print(f"  Duration: {results['duration_seconds']:.1f}s")
    print(f"  Quality Score: {results.get('quality_score', 'N/A')}")
    print(f"  Fix Iterations: {results.get('fix_iterations', 0)}")

    if results.get("quality_breakdown"):
        print("\n  Score Breakdown:")
        for metric, data in results["quality_breakdown"].items():
            score = data.get("score", 0)
            print(f"    {metric}: {score:.2f}")

    print("\n  Stages completed:")
    for stage_name in results.get("stages", {}):
        stage = results["stages"][stage_name]
        status = "error" if stage.get("error") else "ok"
        print(f"    {stage_name}: {status}")

    print("=" * 60)

    # Return quality score as exit code hint
    quality = results.get("quality_score", 0)
    if quality and quality >= 0.8:
        print("\nWorkflow completed successfully!")
        sys.exit(0)
    else:
        print(f"\nWorkflow completed with quality score {quality:.2f} (below 0.8 threshold)")
        sys.exit(1)


if __name__ == "__main__":
    main()
