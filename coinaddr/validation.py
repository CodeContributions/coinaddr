# pylint: disable=E1101

"""
:mod:`coinaddr.validation`
~~~~~~~~~~~~~~~~~~~~~~~~

Various validation machinery for validating cryptocurrency addresses.
"""

import re
import abc
from hashlib import sha256
import functools
import operator

import attr
import sha3
import base58check

from . import currency


class Validators:
    """Container for validator objects."""

    validators = dict()

    @classmethod
    def __getitem__(cls, key):
        return cls.validators[key]

    @classmethod
    def __contains__(cls, key):
        return key in cls.validators

    @classmethod
    def get(cls, key, default=None):
        """Returns validator by name."""
        return cls.validators.get(key, default)


class ValidatorMeta(abc.ABCMeta):
    """Register validator classes on Validators.validators."""

    def __new__(mcs, cls, bases, attrs):
        new = type.__new__(mcs, cls, bases, attrs)
        if new.name and new.name not in Validators.validators:
            Validators.validators[new.name] = new
        return new


@attr.s(cmp=False, slots=True)
class ValidatorBase(metaclass=ValidatorMeta):
    """Validator Interface."""

    name = None
    request = attr.ib(
        type='ValidationRequest',
        validator=lambda i, a, v: type(v).__name__ == 'ValidationRequest'
    )

    @abc.abstractmethod
    def validate(self):
        """Validate the address type, return True if valid, else False."""

    @property
    def network(self):
        """Return the network derived from the network version bytes."""


@attr.s(frozen=True, slots=True, cmp=False)
class Base58CheckValidator(ValidatorBase):
    """Validates Base58Check based cryptocurrency addresses."""

    name = 'Base58Check'

    def validate(self):
        """Validate the address."""
        if 25 > len(self.request.address) > 35:
            return False

        abytes = base58check.b58decode(
            self.request.address, **self.request.extras)
        if not abytes[0] in self.request.networks:
            return False

        checksum = sha256(sha256(abytes[:-4]).digest()).digest()[:4]
        if abytes[-4:] != checksum:
            return False

        return self.request.address == base58check.b58encode(
            abytes, **self.request.extras)

    @property
    def network(self):
        """Return network derived from network version bytes."""
        abytes = base58check.b58decode(
            self.request.address, **self.request.extras)

        nbyte = abytes[0]
        for name, networks in self.request.currency.networks.items():
            if nbyte in networks:
                return name


@attr.s(frozen=True, slots=True, cmp=False)
class EthereumValidator(ValidatorBase):
    """Validates ethereum based crytocurrency addresses."""

    name = 'Ethereum'
    non_checksummed_patterns = (
        re.compile("^(0x)?[0-9a-f]{40}$"), re.compile("^(0x)?[0-9A-F]{40}$")
    )

    def validate(self):
        """Validate the address."""
        address = self.request.address.decode()
        if any(bool(pat.match(address))
               for pat in self.non_checksummed_patterns):
            return True
        addr = address.lstrip('0x')
        addr_hash = sha3.keccak_256(addr.lower().encode('ascii')).hexdigest()
        for i in range(0, len(addr)):
            if any([
                    int(addr_hash[i], 16) > 7 and addr[i].upper() != addr[i],
                    int(addr_hash[i], 16) <= 7 and addr[i].lower() != addr[i]
            ]):
                return False
        return True

    @property
    def network(self):
        """Return network derived from network version bytes."""
        return 'both'


@attr.s(frozen=True, slots=True, cmp=False)
class ValidationRequest:
    """Contain the data and helpers as an immutable request object."""

    _missing = None
    currency = attr.ib(
        type=currency.Currency,
        converter=currency.Currencies.get,
        validator=attr.validators.instance_of(currency.Currency))
    address = attr.ib(
        type=bytes,
        converter=lambda a: a if isinstance(a, bytes) else a.encode('ascii'),
        validator=attr.validators.instance_of(bytes))

    @property
    def extras(self):
        """Extra arguments for passing to decoder, etc."""
        extras = dict()
        if self.currency.charset:
            extras.setdefault('charset', self.currency.charset)
        return extras

    @property
    def networks(self):
        """Concatenated list of all version bytes for currency."""
        networks = tuple(self.currency.networks.values())
        return functools.reduce(operator.concat, networks)

    def execute(self):
        """Execute this request and return the result."""
        validator = Validators.get(self.currency.validator)(self)
        return ValidationResult(
            name=self.currency.name,
            ticker=self.currency.ticker,
            address=self.address,
            valid=validator.validate(),
            network=validator.network
        )


@attr.s(frozen=True, slots=True, cmp=False)
class ValidationResult:
    """Contains an immutable representation of the validation result."""

    name = attr.ib(
        type=str,
        validator=attr.validators.instance_of(str))
    ticker = attr.ib(
        type=str,
        validator=attr.validators.instance_of(str))
    address = attr.ib(
        type=bytes,
        validator=attr.validators.instance_of(bytes))
    valid = attr.ib(
        type=bool,
        validator=attr.validators.instance_of(bool))
    network = attr.ib(
        type=str,
        validator=attr.validators.instance_of(str))


def validate(currency, address):
    """Validate the given address according to currency type.

    This is the main entrypoint for using this library.

    :param currency str: The name or ticker code of the cryptocurrency.
    :param address (bytes, str): The crytocurrency address to validate.
    :return: a populated ValidationResult object
    :rtype: :inst:`ValidationResult`

    Usage::

      >>> import coinaddr
      >>> coinaddr.validate('btc', b'1BoatSLRHtKNngkdXEeobR76b53LETtpyT')
      ValidationResult(name='bitcoin', ticker='btc',
      ...              address=b'1BoatSLRHtKNngkdXEeobR76b53LETtpyT',
      ...              valid=True, network='main')

    """
    request = ValidationRequest(currency, address)
    return request.execute()