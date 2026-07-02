from core_ops import Chain, TargetType, classify_target


def test_bech32_p2wpkh():
    # BIP173 official test vector.
    result = classify_target("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
    assert result.valid
    assert result.chain == Chain.BITCOIN
    assert result.target_type == TargetType.BTC_BECH32


def test_p2pkh_known_real_world_address():
    # Publicly reported (Forbes, 2013) as connected to Ross Ulbricht /
    # Dread Pirate Roberts during the Silk Road seizure — long public,
    # non-sensitive, and used as ChainOps' running demo/test target.
    result = classify_target("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a")
    assert result.valid
    assert result.target_type == TargetType.BTC_P2PKH


def test_p2sh():
    result = classify_target("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    assert result.valid
    assert result.target_type == TargetType.BTC_P2SH


def test_taproot():
    result = classify_target(
        "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297"
    )
    assert result.valid
    assert result.target_type == TargetType.BTC_TAPROOT


def test_bech32_bad_checksum_is_invalid():
    result = classify_target("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")
    assert not result.valid
    assert result.chain == Chain.BITCOIN


def test_base58_bad_checksum_is_invalid():
    result = classify_target("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")
    assert not result.valid


def test_txid():
    txid = "5a4345958085da9da55ac07c69fc36798d87b666ce8646a68ba98d028f546e28"
    result = classify_target(txid)
    assert result.valid
    assert result.chain == Chain.BITCOIN
    assert result.target_type == TargetType.BTC_TXID


def test_block_height():
    result = classify_target("870000")
    assert result.valid
    assert result.target_type == TargetType.BLOCK_HEIGHT


def test_eth_address():
    result = classify_target("0xb2651a809fb0a9ea00b98d500cde6b52d8a13f76")
    assert result.valid
    assert result.chain == Chain.ETHEREUM
    assert result.target_type == TargetType.ETH_ADDRESS


def test_ens_name():
    result = classify_target("vitalik.eth")
    assert result.valid
    assert result.chain == Chain.ETHEREUM
    assert result.target_type == TargetType.ENS_NAME


def test_tron_address():
    result = classify_target("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    assert result.valid
    assert result.chain == Chain.TRON
    assert result.target_type == TargetType.TRON_ADDRESS


def test_unrecognized_target():
    result = classify_target("not-a-real-target!!")
    assert not result.valid
    assert result.chain == Chain.UNKNOWN


def test_strips_whitespace():
    result = classify_target("  870000  ")
    assert result.valid
    assert result.target_type == TargetType.BLOCK_HEIGHT
