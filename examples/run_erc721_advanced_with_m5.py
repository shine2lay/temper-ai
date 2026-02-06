#!/usr/bin/env python3
"""
Advanced ERC721 Generator with M5 Self-Improvement Integration

A harder version of the ERC721 demo where the LLM must generate complex
Solidity code from requirements (not copy verbatim code). The contract
includes ERC721Enumerable, URIStorage, Pausable, max supply, mint price,
and withdrawal — with 12 tests covering all features.

Usage:
    python examples/run_erc721_advanced_with_m5.py --model qwen3-next --iterations 2
"""
import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from examples.run_erc721_generator import (
    check_prerequisites,
    create_workspace,
    run_agent_with_input,
)
from src.self_improvement.strategies.strategy import LearnedPattern

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Advanced contract defaults
DEFAULT_CONTRACT_NAME = "AdvancedNFT"
DEFAULT_TOKEN_NAME = "AdvancedNFT"
DEFAULT_TOKEN_SYMBOL = "ANFT"

# Agent config paths
ADVANCED_CONFIGS = {
    "architect": "configs/agents/erc721_advanced_architect.yaml",
    "coder": "configs/agents/erc721_advanced_coder.yaml",
    "tester": "configs/agents/erc721_advanced_tester.yaml",
    "fixer": "configs/agents/erc721_advanced_fixer.yaml",
}

# Scoring weights for advanced contract
ADVANCED_WEIGHTS = {
    "project_structure": 0.10,
    "compilation": 0.25,
    "tests_pass": 0.30,
    "code_quality": 0.15,
    "advanced_features": 0.10,
    "deployment": 0.10,
}


def run_direct_setup_advanced(
    workspace: Path,
    contract_name: str,
    token_name: str,
    token_symbol: str,
) -> bool:
    """Deterministic fallback that writes the advanced ERC721 project files.

    This is the reference implementation. If the LLM fails to produce valid
    code, this ensures we still have a working project for scoring.

    Args:
        workspace: Workspace directory path
        contract_name: Solidity contract name
        token_name: ERC721 token name
        token_symbol: ERC721 token symbol

    Returns:
        True if setup succeeded
    """
    logger.info("Writing advanced project files (deterministic fallback)...")

    # package.json
    package_json = {
        "name": "erc721-advanced-project",
        "version": "1.0.0",
        "description": "Advanced ERC721 NFT project with Enumerable, URIStorage, Pausable",
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
    hardhat_config = (
        'require("@nomicfoundation/hardhat-toolbox");\n\n'
        "module.exports = {\n"
        '  solidity: "0.8.20",\n'
        "};\n"
    )
    (workspace / "hardhat.config.js").write_text(hardhat_config)

    # contracts/
    (workspace / "contracts").mkdir(exist_ok=True)
    contract_sol = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {contract_name} is ERC721, ERC721Enumerable, ERC721URIStorage, ERC721Pausable, Ownable {{
    uint256 public constant MAX_SUPPLY = 1000;
    uint256 public constant MINT_PRICE = 0.01 ether;
    uint256 private _nextTokenId;

    constructor() ERC721("{token_name}", "{token_symbol}") Ownable(msg.sender) {{
        _nextTokenId = 1;
    }}

    function mint(address to, string memory uri) public payable {{
        require(msg.value >= MINT_PRICE, "Insufficient payment");
        require(_nextTokenId <= MAX_SUPPLY, "Max supply reached");

        uint256 tokenId = _nextTokenId;
        _nextTokenId++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);
    }}

    function ownerMint(address to, string memory uri) public onlyOwner {{
        require(_nextTokenId <= MAX_SUPPLY, "Max supply reached");

        uint256 tokenId = _nextTokenId;
        _nextTokenId++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);
    }}

    function pause() public onlyOwner {{
        _pause();
    }}

    function unpause() public onlyOwner {{
        _unpause();
    }}

    function withdraw() public onlyOwner {{
        uint256 balance = address(this).balance;
        require(balance > 0, "No balance to withdraw");
        (bool success, ) = payable(owner()).call{{value: balance}}("");
        require(success, "Withdraw failed");
    }}

    // Required overrides for multiple inheritance
    function _update(address to, uint256 tokenId, address auth)
        internal
        override(ERC721, ERC721Enumerable, ERC721Pausable)
        returns (address)
    {{
        return super._update(to, tokenId, auth);
    }}

    function _increaseBalance(address account, uint128 value)
        internal
        override(ERC721, ERC721Enumerable)
    {{
        super._increaseBalance(account, value);
    }}

    function tokenURI(uint256 tokenId)
        public
        view
        override(ERC721, ERC721URIStorage)
        returns (string memory)
    {{
        return super.tokenURI(tokenId);
    }}

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, ERC721Enumerable, ERC721URIStorage)
        returns (bool)
    {{
        return super.supportsInterface(interfaceId);
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
  const MINT_PRICE = ethers.parseEther("0.01");

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

    it("Should have zero total supply initially", async function () {{
      expect(await contract.totalSupply()).to.equal(0);
    }});
  }});

  describe("Minting", function () {{
    it("Should mint with correct payment and set tokenURI", async function () {{
      await contract.mint(addr1.address, "ipfs://token1", {{ value: MINT_PRICE }});
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
      expect(await contract.tokenURI(1)).to.equal("ipfs://token1");
    }});

    it("Should reject minting with insufficient payment", async function () {{
      await expect(
        contract.mint(addr1.address, "ipfs://token1", {{ value: 0 }})
      ).to.be.revertedWith("Insufficient payment");
    }});

    it("Should allow owner to mint for free", async function () {{
      await contract.ownerMint(addr1.address, "ipfs://free1");
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
      expect(await contract.tokenURI(1)).to.equal("ipfs://free1");
    }});

    it("Should increment token IDs and update totalSupply", async function () {{
      await contract.mint(addr1.address, "ipfs://1", {{ value: MINT_PRICE }});
      await contract.mint(addr2.address, "ipfs://2", {{ value: MINT_PRICE }});
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
      expect(await contract.ownerOf(2)).to.equal(addr2.address);
      expect(await contract.totalSupply()).to.equal(2);
    }});
  }});

  describe("Pausable", function () {{
    it("Should allow owner to pause and unpause", async function () {{
      await contract.pause();
      await contract.unpause();
      // Should work normally after unpause
      await contract.ownerMint(addr1.address, "ipfs://1");
      expect(await contract.ownerOf(1)).to.equal(addr1.address);
    }});

    it("Should reject transfers when paused", async function () {{
      await contract.ownerMint(addr1.address, "ipfs://1");
      await contract.pause();
      await expect(
        contract.connect(addr1).transferFrom(addr1.address, addr2.address, 1)
      ).to.be.revertedWithCustomError(contract, "EnforcedPause");
    }});
  }});

  describe("Withdraw", function () {{
    it("Should allow owner to withdraw ETH", async function () {{
      await contract.mint(addr1.address, "ipfs://1", {{ value: MINT_PRICE }});
      const contractBalance = await ethers.provider.getBalance(await contract.getAddress());
      expect(contractBalance).to.equal(MINT_PRICE);
      await contract.withdraw();
      const newBalance = await ethers.provider.getBalance(await contract.getAddress());
      expect(newBalance).to.equal(0);
    }});

    it("Should reject non-owner withdrawal", async function () {{
      await expect(
        contract.connect(addr1).withdraw()
      ).to.be.revertedWithCustomError(contract, "OwnableUnauthorizedAccount");
    }});
  }});

  describe("Transfer", function () {{
    it("Should transfer tokens between accounts", async function () {{
      await contract.ownerMint(addr1.address, "ipfs://1");
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

  // Owner mint a test token
  const tx = await contract.ownerMint(deployer.address, "ipfs://genesis");
  await tx.wait();
  console.log("Minted token #1 to:", deployer.address);
  console.log("Token URI:", await contract.tokenURI(1));
  console.log("Total supply:", (await contract.totalSupply()).toString());
}}

main()
  .then(() => process.exit(0))
  .catch((error) => {{
    console.error(error);
    process.exit(1);
  }});
"""
    (workspace / "scripts" / "deploy.js").write_text(deploy_js)

    logger.info("All advanced project files written successfully")

    # npm install
    logger.info("Running npm install...")
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


def score_advanced_code_quality(
    workspace: Path, contract_name: str = "AdvancedNFT"
) -> Dict[str, Any]:
    """Score code quality with checks specific to the advanced contract.

    Checks for advanced features beyond basic ERC721.

    Args:
        workspace: Path to workspace directory
        contract_name: Contract name

    Returns:
        Dict with 'score' and 'details'
    """
    contract_path = workspace / "contracts" / f"{contract_name}.sol"
    if not contract_path.exists():
        contracts_dir = workspace / "contracts"
        if contracts_dir.exists():
            sol_files = list(contracts_dir.glob("*.sol"))
            if sol_files:
                contract_path = sol_files[0]
            else:
                return {"score": 0.0, "details": "No .sol files found"}
        else:
            return {"score": 0.0, "details": "No contracts/ directory"}

    try:
        content = contract_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"score": 0.0, "details": f"Cannot read contract: {e}"}

    checks = {
        "imports_erc721": "ERC721" in content,
        "has_constructor": "constructor" in content,
        "has_spdx": "SPDX-License-Identifier" in content,
        "has_pragma": "pragma solidity" in content,
        "imports_ownable": "Ownable" in content,
        "has_mint": "function mint" in content or "function safeMint" in content,
    }

    passed = sum(1 for v in checks.values() if v)
    score = passed / len(checks)

    return {"score": score, "details": checks}


def score_advanced_features(
    workspace: Path, contract_name: str = "AdvancedNFT"
) -> Dict[str, Any]:
    """Score presence of advanced features in the contract.

    These are the features the LLM must implement beyond basic ERC721.

    Args:
        workspace: Path to workspace directory
        contract_name: Contract name

    Returns:
        Dict with 'score' and 'details'
    """
    contract_path = workspace / "contracts" / f"{contract_name}.sol"
    if not contract_path.exists():
        contracts_dir = workspace / "contracts"
        if contracts_dir.exists():
            sol_files = list(contracts_dir.glob("*.sol"))
            if sol_files:
                contract_path = sol_files[0]
            else:
                return {"score": 0.0, "details": "No .sol files found"}
        else:
            return {"score": 0.0, "details": "No contracts/ directory"}

    try:
        content = contract_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"score": 0.0, "details": f"Cannot read contract: {e}"}

    features = {
        "enumerable": "ERC721Enumerable" in content,
        "uri_storage": "ERC721URIStorage" in content,
        "pausable": "ERC721Pausable" in content or "Pausable" in content,
        "max_supply": "MAX_SUPPLY" in content or "maxSupply" in content,
        "mint_price": "MINT_PRICE" in content or "mintPrice" in content or "0.01 ether" in content,
        "withdraw": "function withdraw" in content,
        "owner_mint": "function ownerMint" in content or "function adminMint" in content,
        "override_update": "_update" in content and "override" in content,
    }

    passed = sum(1 for v in features.values() if v)
    score = passed / len(features)

    return {"score": score, "details": features}


def score_advanced_project_structure(
    workspace: Path, contract_name: str = "AdvancedNFT"
) -> Dict[str, Any]:
    """Score project structure for advanced project.

    Args:
        workspace: Path to workspace directory
        contract_name: Contract name

    Returns:
        Dict with 'score' and 'details'
    """
    if not workspace.exists():
        return {"score": 0.0, "details": "Workspace does not exist"}

    found = []
    missing = []

    check_files = [
        "package.json",
        "hardhat.config.js",
        f"contracts/{contract_name}.sol",
        f"test/{contract_name}.test.js",
        "scripts/deploy.js",
        "node_modules/",
    ]

    for fname in check_files:
        path = workspace / fname
        if path.exists():
            found.append(fname)
        else:
            missing.append(fname)

    score = len(found) / len(check_files) if check_files else 0.0
    return {"score": min(1.0, score), "details": {"found": found, "missing": missing}}


def score_command(
    workspace: Path, command: List[str], timeout: int = 120
) -> Dict[str, Any]:
    """Run a command and score pass/fail.

    Args:
        workspace: Working directory
        command: Command to run
        timeout: Timeout in seconds

    Returns:
        Dict with 'score' and 'details'
    """
    if not workspace.exists() or not (workspace / "hardhat.config.js").exists():
        return {"score": 0.0, "details": "No hardhat.config.js found"}

    try:
        result = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        stdout = result.stdout
        passing = 0
        failing = 0

        for line in stdout.split("\n"):
            line_stripped = line.strip()
            if "passing" in line_stripped.lower():
                try:
                    passing = int(line_stripped.split()[0])
                except (ValueError, IndexError):
                    pass
            if "failing" in line_stripped.lower():
                try:
                    failing = int(line_stripped.split()[0])
                except (ValueError, IndexError):
                    pass

        if result.returncode == 0:
            score = 1.0
        elif passing > 0 and failing > 0:
            score = passing / (passing + failing)
        else:
            score = 0.0

        return {
            "score": score,
            "details": {
                "passing": passing,
                "failing": failing,
                "exit_code": result.returncode,
                "stdout": stdout[:500],
                "stderr": result.stderr[:500],
            },
        }
    except subprocess.TimeoutExpired:
        return {"score": 0.0, "details": "Timed out"}
    except FileNotFoundError:
        return {"score": 0.0, "details": "npx not found"}
    except Exception as e:
        return {"score": 0.0, "details": f"Error: {e}"}


def score_advanced_workflow(
    workspace_path: str,
    contract_name: str = "AdvancedNFT",
    run_commands: bool = True,
    timeout: int = 120,
) -> Dict[str, Any]:
    """Score a complete advanced ERC721 workflow run.

    Args:
        workspace_path: Path to workspace directory
        contract_name: Contract name
        run_commands: Whether to run compile/test/deploy
        timeout: Timeout per command

    Returns:
        Dict with 'total_score' and 'breakdown'
    """
    workspace = Path(workspace_path)
    breakdown = {}

    # 1. Project structure (10%)
    breakdown["project_structure"] = score_advanced_project_structure(
        workspace, contract_name
    )

    # 2. Compilation (25%)
    if run_commands:
        breakdown["compilation"] = score_command(
            workspace, ["npx", "hardhat", "compile"], timeout
        )
    else:
        breakdown["compilation"] = {"score": 0.0, "details": "Skipped"}

    # 3. Tests (30%)
    if run_commands and breakdown["compilation"]["score"] > 0:
        breakdown["tests_pass"] = score_command(
            workspace, ["npx", "hardhat", "test"], timeout
        )
    else:
        breakdown["tests_pass"] = {"score": 0.0, "details": "Skipped (compilation failed)"}

    # 4. Code quality (15%)
    breakdown["code_quality"] = score_advanced_code_quality(workspace, contract_name)

    # 5. Advanced features (10%)
    breakdown["advanced_features"] = score_advanced_features(workspace, contract_name)

    # 6. Deployment (10%)
    if run_commands and breakdown["compilation"]["score"] > 0:
        breakdown["deployment"] = score_command(
            workspace, ["npx", "hardhat", "run", "scripts/deploy.js"], timeout
        )
    else:
        breakdown["deployment"] = {"score": 0.0, "details": "Skipped"}

    # Weighted total
    total = sum(
        breakdown[metric]["score"] * weight
        for metric, weight in ADVANCED_WEIGHTS.items()
    )
    total = max(0.0, min(1.0, total))

    return {"total_score": total, "breakdown": breakdown}


def run_advanced_workflow(
    workspace: Path,
    contract_name: str = "AdvancedNFT",
    token_name: str = "AdvancedNFT",
    token_symbol: str = "ANFT",
    llm_model: str = "qwen3-next",
    use_llm: bool = True,
    max_fix_loops: int = 3,
) -> Dict:
    """Run the complete advanced ERC721 generation workflow.

    Stages:
    1. Scaffold (architect plans structure)
    2. Code (LLM writes complex contract + tests from requirements)
    3. Test (compile + run tests)
    4. Fix (if tests fail, fix and re-test)

    Args:
        workspace: Workspace directory
        contract_name: Contract name
        token_name: Token name
        token_symbol: Token symbol
        llm_model: Ollama model
        use_llm: Whether to use LLM
        max_fix_loops: Max fix iterations

    Returns:
        Results dict with quality score
    """
    start_time = time.time()
    results = {
        "workspace": str(workspace),
        "contract_name": contract_name,
        "stages": {},
        "quality_score": None,
        "duration_seconds": 0,
        "llm_generated": False,
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
        logger.info("STAGE 1: Scaffold (Advanced Architect)")
        logger.info("=" * 60)
        try:
            scaffold_result = run_agent_with_input(
                ADVANCED_CONFIGS["architect"],
                input_data,
                llm_model,
            )
            results["stages"]["scaffold"] = scaffold_result
            input_data["stage_outputs"]["scaffold"] = scaffold_result.get("output", "")
            logger.info(f"Scaffold complete (tokens: {scaffold_result.get('tokens', 0)})")
        except Exception as e:
            logger.warning(f"Scaffold agent failed: {e}. Continuing.")
            results["stages"]["scaffold"] = {"error": str(e)}

        # Stage 2: Code (LLM writes the complex contract)
        logger.info("=" * 60)
        logger.info("STAGE 2: Code (Advanced Coder - LLM generates code)")
        logger.info("=" * 60)
        try:
            code_result = run_agent_with_input(
                ADVANCED_CONFIGS["coder"],
                input_data,
                llm_model,
            )
            results["stages"]["code"] = code_result
            input_data["stage_outputs"]["code"] = code_result.get("output", "")
            logger.info(f"Code complete (tokens: {code_result.get('tokens', 0)})")
        except Exception as e:
            logger.warning(f"Coder agent failed: {e}. Falling back to deterministic setup.")
            results["stages"]["code"] = {"error": str(e)}
    else:
        logger.info("=" * 60)
        logger.info("Running in deterministic mode (no LLM)")
        logger.info("=" * 60)
        success = run_direct_setup_advanced(workspace, contract_name, token_name, token_symbol)
        results["stages"]["direct_setup"] = {"success": success}

    # Check if LLM produced files (no deterministic fallback)
    if not (workspace / "package.json").exists():
        logger.error("LLM failed to produce project files. No fallback — scoring will reflect this.")
        results["llm_generated"] = False
    else:
        results["llm_generated"] = True

    # Stage 3: Test
    logger.info("=" * 60)
    logger.info("STAGE 3: Test (Compile + Test)")
    logger.info("=" * 60)

    if use_llm:
        try:
            test_result = run_agent_with_input(
                ADVANCED_CONFIGS["tester"],
                input_data,
                llm_model,
            )
            results["stages"]["test"] = test_result
            input_data["stage_outputs"]["test"] = test_result.get("output", "")
        except Exception as e:
            logger.warning(f"Tester agent failed: {e}. Running directly.")
            results["stages"]["test"] = {"error": str(e)}
    else:
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
        except Exception as e:
            results["stages"]["test"] = {"error": str(e)}

    # Stage 4: Fix (conditional)
    fix_iterations = 0
    if use_llm:
        for i in range(max_fix_loops):
            test_output = input_data.get("stage_outputs", {}).get("test", "")
            test_str = str(test_output).lower()

            # Check if compilation failed — always need fix if compilation failed
            compilation_failed = (
                '"compilation failed"' in test_str
                or '"success": false' in test_str
                or "error hh600" in test_str
            )
            if compilation_failed:
                logger.info("Compilation failed. Running fix stage.")
            elif "passing" in test_str and "failing" not in test_str:
                logger.info("Tests appear to pass. Skipping fix stage.")
                break
            elif '"failing": 0' in test_str and '"success": true' in test_str:
                logger.info("Tests passing. Skipping fix stage.")
                break

            logger.info("=" * 60)
            logger.info(f"STAGE 4: Fix (iteration {i + 1}/{max_fix_loops})")
            logger.info("=" * 60)

            try:
                fix_result = run_agent_with_input(
                    ADVANCED_CONFIGS["fixer"],
                    input_data,
                    llm_model,
                )
                results["stages"][f"fix_{i + 1}"] = fix_result
                input_data["stage_outputs"]["fix"] = fix_result.get("output", "")
                fix_iterations += 1

                # Re-test after fix
                test_result = run_agent_with_input(
                    ADVANCED_CONFIGS["tester"],
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
    logger.info("SCORING: Advanced Quality Assessment")
    logger.info("=" * 60)

    try:
        quality = score_advanced_workflow(
            workspace_path=str(workspace),
            contract_name=contract_name,
            run_commands=True,
        )
        results["quality_score"] = quality["total_score"]
        results["quality_breakdown"] = quality["breakdown"]
        logger.info(f"Quality Score: {quality['total_score']:.2f}")
        for metric, data in quality["breakdown"].items():
            logger.info(f"  {metric}: {data['score']:.2f}")
            details = data.get("details", {})
            if isinstance(details, dict):
                if "stdout" in details and details["stdout"]:
                    logger.info(f"    stdout: {details['stdout'][:200]}")
                if "stderr" in details and details["stderr"]:
                    logger.info(f"    stderr: {details['stderr'][:200]}")
                if "passing" in details:
                    logger.info(f"    passing: {details['passing']}, failing: {details['failing']}")
    except Exception as e:
        logger.error(f"Quality scoring failed: {e}")
        results["quality_score"] = 0.0

    results["duration_seconds"] = time.time() - start_time
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Advanced ERC721 Generator with M5 Self-Improvement",
    )
    parser.add_argument("--model", default="qwen3-next", help="Ollama model name")
    parser.add_argument(
        "--contract-name", default=DEFAULT_CONTRACT_NAME, help="Contract name"
    )
    parser.add_argument(
        "--token-name", default=DEFAULT_TOKEN_NAME, help="Token name"
    )
    parser.add_argument(
        "--token-symbol", default=DEFAULT_TOKEN_SYMBOL, help="Token symbol"
    )
    parser.add_argument(
        "--iterations", type=int, default=2, help="Number of M5 iterations"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Deterministic mode (no LLM)"
    )
    parser.add_argument(
        "--max-fix-loops", type=int, default=3, help="Max fix-test iterations per run"
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(PROJECT_ROOT / "workspace"),
        help="Base workspace directory",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Advanced ERC721 Generator with M5 Self-Improvement")
    print("=" * 60)
    print(f"  Model: {args.model}")
    print(f"  Contract: {args.contract_name}")
    print("  Features: Enumerable, URIStorage, Pausable, MintPrice, MaxSupply, Withdraw")
    print(f"  Iterations: {args.iterations}")
    print(f"  LLM: {'Disabled' if args.no_llm else 'Enabled'}")
    print("=" * 60)

    if not check_prerequisites():
        logger.error("Prerequisites not met.")
        sys.exit(1)

    workspace_base = Path(args.workspace_dir)
    all_results = []
    patterns: List[LearnedPattern] = []

    for iteration in range(1, args.iterations + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"  ITERATION {iteration}")
        logger.info(f"  Model: {args.model}")
        logger.info(f"{'='*60}")

        workspace = create_workspace(workspace_base)

        results = run_advanced_workflow(
            workspace=workspace,
            contract_name=args.contract_name,
            token_name=args.token_name,
            token_symbol=args.token_symbol,
            llm_model=args.model,
            use_llm=not args.no_llm,
            max_fix_loops=args.max_fix_loops,
        )
        results["iteration"] = iteration
        results["model"] = args.model
        all_results.append(results)

        quality = results.get("quality_score", 0.0) or 0.0
        logger.info(f"\nIteration {iteration} quality score: {quality:.2f}")
        logger.info(f"LLM generated: {results.get('llm_generated', False)}")

        # M5 improvement analysis
        if quality < 0.8 and iteration < args.iterations:
            patterns.append(
                LearnedPattern(
                    pattern_type="low_quality" if quality < 0.5 else "high_error_rate",
                    description=f"Iteration {iteration}: quality={quality:.2f}",
                    support=1,
                    confidence=min(0.9, 0.5 + iteration * 0.1),
                    evidence={
                        "quality_score": quality,
                        "iteration": iteration,
                        "model": args.model,
                        "llm_generated": results.get("llm_generated", False),
                    },
                )
            )

    # Final comparison
    print("\n" + "=" * 60)
    print("  ADVANCED M5 SELF-IMPROVEMENT RESULTS")
    print("=" * 60)

    for r in all_results:
        it = r.get("iteration", "?")
        model = r.get("model", "?")
        quality = r.get("quality_score", 0.0) or 0.0
        duration = r.get("duration_seconds", 0.0)
        llm_gen = r.get("llm_generated", False)
        fix_its = r.get("fix_iterations", 0)

        print(f"\n  Iteration {it}:")
        print(f"    Model: {model}")
        print(f"    Quality: {quality:.2f}")
        print(f"    Duration: {duration:.1f}s")
        print(f"    LLM Generated: {llm_gen}")
        print(f"    Fix Iterations: {fix_its}")

        breakdown = r.get("quality_breakdown", {})
        if breakdown:
            for metric, data in breakdown.items():
                if isinstance(data, dict):
                    score = data.get("score", "N/A")
                    print(f"    {metric}: {score}")
                    details = data.get("details", {})
                    if isinstance(details, dict) and "passing" in details:
                        print(
                            f"      passing: {details['passing']}, failing: {details['failing']}"
                        )

    if len(all_results) >= 2:
        first_q = all_results[0].get("quality_score", 0) or 0
        last_q = all_results[-1].get("quality_score", 0) or 0
        delta = last_q - first_q
        print(
            f"\n  Improvement: {first_q:.2f} -> {last_q:.2f} "
            f"({'+' if delta >= 0 else ''}{delta:.2f})"
        )

    print("=" * 60)


if __name__ == "__main__":
    main()
