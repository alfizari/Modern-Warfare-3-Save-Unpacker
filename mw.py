import dd as dd

def read_file(path):

    if path is None:
        return
    
    with open(path, 'rb') as f:
        data=f.read()

    return data

def write_file(data, path):

    if path is None:
        return
    
    with open(path, 'wb') as f:
        f.write(data)

    return True

def decompress_file(data):

    decompressed_data, prefix, trailing, stream_start=dd.decompress(data)



    return decompressed_data, stream_start


def compress_file(data, original_compressed_data=None):



    decompressed_data, prefix, trailing, stream_start = dd.decompress(original_compressed_data)

    re_comp_data = dd.compress(data)

    rebuilt_data = prefix + re_comp_data + trailing  

    return rebuilt_data

# path='C:\\Users\\alfazari911\\Desktop\\mw3 com\\unpacked\\npdata'

# data=read_file(path)

# comp_data=decompress_file(data)

# write_file(comp_data, path+'comp')

# path_dec='C:\\Users\\alfazari911\\Desktop\\mw3 com\\unpacked\\npdatacomp.fixed'

# re_data=read_file(path_dec)
# re_com=compress_file(re_data, data)
# write_file(re_com, path_dec+'re')