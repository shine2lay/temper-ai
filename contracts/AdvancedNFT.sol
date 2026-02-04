// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract AdvancedNFT is ERC721, ERC721Enumerable, ERC721URIStorage, ERC721Pausable, Ownable {
    uint256 public constant MAX_SUPPLY = 1000;
    uint256 public constant MINT_PRICE = 0.01 ether;

    uint256 private _tokenIds;

    constructor() ERC721("AdvancedNFT", "ANFT") {
        _tokenIds = 0;
    }

    function mint(address to, string memory uri) public payable {
        require(msg.value == MINT_PRICE, "Incorrect amount");
        require(totalSupply() < MAX_SUPPLY, "Max supply reached");
        _safeMint(to, _tokenIds);
        _setTokenURI(_tokenIds, uri);
        _tokenIds++;
    }

    function ownerMint(address to, string memory uri) public onlyOwner {
        require(totalSupply() < MAX_SUPPLY, "Max supply reached");
        _safeMint(to, _tokenIds);
        _setTokenURI(_tokenIds, uri);
        _tokenIds++;
    }

    function pause() public onlyOwner {
        _pause();
    }

    function unpause() public onlyOwner {
        _unpause();
    }

    function withdraw() public onlyOwner {
        payable(owner()).transfer(address(this).balance);
    }

    function _beforeTokenTransfer(address from, address to, uint256 tokenId, uint256 batchSize) internal override(ERC721, ERC721Enumerable) {
        super._beforeTokenTransfer(from, to, tokenId, batchSize);
    }

    function _afterTokenTransfer(address from, address to, uint256 tokenId, uint256 batchSize) internal override(ERC721, ERC721Enumerable) {
        super._afterTokenTransfer(from, to, tokenId, batchSize);
    }

    function tokenURI(uint256 tokenId) public view override(ERC721, ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC721, ERC721Enumerable, ERC721URIStorage) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}