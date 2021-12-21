''' MIPS definition classes. '''

import types
import collections


class ISAError(Exception):
    pass

#-----------------------------------------------------------------------
def mask(n):
    '''Return an n-bit bit mask (e.g mask(3) returns 0x7).'''
    return (1<<n)-1

assert mask(3) == 0x7

#-----------------------------------------------------------------------
def bit_select(value, upper_bit, lower_bit, shift=False):
    '''Mask out all but a field of bits (from upper->lower inclusive).'''
    if upper_bit < lower_bit:
        raise ISAError(f'upper_bit "{upper_bit}" is lower than lower_bit "{lower_bit}".')
    smask = mask(upper_bit+1) & ~mask(lower_bit)
    shamt = lower_bit if shift else 0
    return (value & smask) >> shamt

#     bit position: 543210
assert bit_select(0b111111,3,1) == 0b01110
assert bit_select(0b111000,3,1) == 0b01000
assert bit_select(0b111111,2,2) == 0b00100
assert bit_select(0b111000,3,1,shift=True) == 0b0100
assert bit_select(0b111111,2,2,shift=True) == 0b001

#-----------------------------------------------------------------------
def sign_extend(i, bits):
    '''Sign extend a set of bits.'''
    upper_mask = ~mask(bits)
    if i & upper_mask != 0:
        raise ISAError(f'upper bits of i "{i}" not 0.')

    if i & (1<<(bits-1)) == 0:
        return i
    else:
        return i | upper_mask

assert sign_extend(0b1111,4) == -1
assert sign_extend(0b1000,4) == -8
assert sign_extend(0b0000,4) == 0
assert sign_extend(0b0111,4) == 7


#-----------------------------------------------------------------------

# Error checking to add:
# 1) check if function name and op in docstring mismatch

class  IsaDefinition:
    ''' A base class for defining ISAs. '''

    def __init__(self):
        self._ifuncs = [getattr(self,f) for f in dir(self) if f.startswith('instruction_')]
        self._reg_list = []
        self._mem = None
        # the parameters below are set by default but can be overridden in derived classes
        self.endian = 'big'  # can be either 'big' or 'little'
        self.isize = 4  # width of an instruction in bytes

    def make_register(self, name, bits=32):
        '''Add a special purpose register to the machine specification.'''
        setattr(self, name, 0)
        self._reg_list.append(('reg',name,bits,None,None))
        #self.mask[name] = (1<<bits)-1

    def make_register_file(self, name, size, bits=32, rnames=None):
        '''Add a register file to the machine specification.'''
        setattr(self, name, {x:0 for x in range(size)})
        if rnames is None:
            rnames = {x:f'${name}{x}' for x in range(size)}
        self._reg_list.append(('file',name,bits,size,rnames))

    def registers(self):
        '''Generates a triple of information for each register (name, bitwidth, value).'''
        for rtype, name, bits, size, rnames in self._reg_list:
            if rtype=='reg':
                yield name, bits, getattr(self, name)
            else:
                assert rtype=='file'
                for i in range(size):
                    yield rnames[i], bits, getattr(self, name)[i]

    def _extract_pattern(self, func):
        '''Extract an patterns from the instruction function docstring.'''
        # string should look like 'add immediate : 001000 sssss ttttt iiiiiiiiiii: something'
        docstring = func.__doc__
        clean_format = docstring.replace(' ','').split(':')[1]
        if len(clean_format) != self.isize*8:
            raise ISAError(f'format for "{clean_format}" is {len(clean_format)} bits not {self.isize*8}.')
        return clean_format

    def _pattern_match(self, ifunc, instr):
        '''Check if a function docstring matches the instr provided, return fields or None.'''
        if len(instr) != self.isize:
            raise ISAError(f'instruction "{instr}" is {len(instr)} bytes not {self.isize}.')
        pattern = self._extract_pattern(ifunc)
        instr_as_integer = int.from_bytes(instr, self.endian)
        instr_as_list_of_bits = [(instr_as_integer>>(s-1)) & 0x1 for s in range(self.isize*8,0,-1)]
        fields = collections.defaultdict(int)

        for bpattern, bit in zip(pattern, instr_as_list_of_bits):
            if bpattern=='0' and bit==1:
                return None
            elif bpattern=='1' and bit==0:
                return None
            else:
                fields[bpattern] = (fields[bpattern] << 1) | bit
        ifield = types.SimpleNamespace(**fields)
        return ifield

    def _extract_asm(self, ifunction):
        '''Given an instruction_func, return a clean asm definition from docstring.'''
        asm_pattern = ifunction.__doc__.split(':')[2]
        clean_pattern = asm_pattern.replace(',',' ').strip()
        monospaced_pattern = str.join(' ', clean_pattern.split())
        return monospaced_pattern

    def _format_asm(self, asm_pattern, ifield):
        def operand_field(part, indicator):
            # TODO much better error handling
            fchar = part[1:]
            assert len(fchar)==1
            return getattr(ifield, fchar)

        instruction = []
        for i,part in enumerate(asm_pattern.split()):
            if i==0:
                instruction.append(part)  # instruction name
            elif part.startswith('$'):
                rnum = operand_field(part, '$')
                instruction.append(f'${rnum}')
            elif part.startswith('@'):
                addr = operand_field(part, '@')
                instruction.append(f'{hex(addr<<2)}')
            elif part.startswith('!'):
                immed = operand_field(part, '!')
                instruction.append(f'{hex(immed)}')
            else:
                raise ISAError(f'Unknown operand specifier: "{part}" in "{asm_pattern}"')
        return str.join(' ', instruction)

    def fetch(self):
        '''Fetch the next instruction at PC and return as an array of bytes.'''
        return self.mem_read(self.PC, self.isize)

    def decode(self, instr):
        '''Given an instruction (as array of bytes) return its decoded form.'''
        for ifunc in self._ifuncs:
            ifield = self._pattern_match(ifunc, instr)
            if ifield is not None:
                return ifunc, ifield
        raise ISAError(f'Unable to decode bytes as instruction:"{instr}".')

    def execute(self, decoded_instr):
        '''Execute a decoded instruction.'''
        ifunction, ifield = decoded_instr
        ifunction(ifield)

    def istring(self, decoded_instr):
        '''Return a string representation of a decoded instruction.'''
        ifunction, ifield = decoded_instr
        asm_pattern = self._extract_asm(ifunction)
        instr_string = self._format_asm(asm_pattern, ifield)
        return instr_string

    def step(self):
        '''Step the simulator forward and return a string of instruction executed.'''
        instr_mem = self.fetch()
        decoded_instr = self.decode(instr_mem)
        self.execute(decoded_instr)
        if hasattr(self,'finalize_execution'):
            self.finalize_execution(decoded_instr)
        return self.istring(decoded_instr)

    def mem_map(self, start_address, size):
        '''Map a region of physical memory into the simulator.'''
        print('Warning: memory map not fully implemented -- assuming start_address is zero')
        self._mem = bytearray(size)

    def mem_read(self, start_addr, size):
        '''Read a region of memory and return an array of bytes.'''
        return self._mem[start_addr:start_addr+size]

    def mem_write(self, start_addr, data):
        '''Write an array of bytes into memory.'''
        self._mem[start_addr:start_addr+len(data)] = data